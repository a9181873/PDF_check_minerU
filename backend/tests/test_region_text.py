import subprocess
import threading

import fitz
import pytest

from models.diff_models import BBox
from services import region_text_service as service


def glyphs(lines):
    return [service.Glyph(char, BBox(page=1, x0=20+i*9, y0=700-row*16, x1=29+i*9,
                                    y1=711-row*16), .96, (1, 1, row))
            for row, text in enumerate(lines) for i, char in enumerate(text)]


def test_reflowed_identical_paragraph_is_not_an_addition():
    old = glyphs(["被保險人於本契約有效期間內因疾病住院", "保險公司依約給付住院日額保險金"])
    new = glyphs(["被保險人於本契約有效期間內", "因疾病住院保險公司依約給付", "住院日額保險金"])
    assert service.confirmed_additions(new, new, old, old) == []


def test_new_clause_needs_both_reads_and_unchanged_context():
    before, after = "被保險人於本契約有效期間內因疾病住院", "保險公司依約給付住院日額保險金"
    clause = "給付時須扣除已領取之各項保險金總額"
    old, new = glyphs([before, after]), glyphs([before, clause, after])
    result = service.confirmed_additions(new, new, old, old)
    assert len(result) == 1
    assert result[0][0] == clause
    assert result[0][2] is None
    # An OCR omission on one side cannot prove the clause is new.
    assert service.confirmed_additions(new, new, old, new) == []
    assert service.confirmed_additions(new, old, old, old) == []
    assert service.confirmed_additions(glyphs([clause]), glyphs([clause]), [], []) == []


@pytest.mark.parametrize("new", ["本契約不保證續保且保險公司依約給付保險金", "本契約保證續保且保險公司依約給付保險鑫"])
def test_negation_and_single_glyph_changes_are_never_fabricated_additions(new):
    old = glyphs(["本契約保證續保且保險公司依約給付保險金"])
    assert service.confirmed_additions(glyphs([new]), glyphs([new]), old, old) == []


def test_header_columns_do_not_cut_body_table_column():
    with fitz.open() as doc:
        p = doc.new_page(width=595, height=842)
        for x in (40, 120, 390, 550):
            p.draw_line((x, 200), (x, 780), width=1, color=(.2, .4, .5))
        for x in (295, 374):
            p.draw_line((x, 130), (x, 155), width=1, color=(.2, .4, .5))
        rules = service._vertical_rules(p, fitz.Rect(30, 100, 560, 790))
        assert any(abs(x-120) < 2 for x in rules)
        assert any(abs(x-390) < 2 for x in rules)
        assert not any(abs(x-295) < 2 or abs(x-374) < 2 for x in rules)


def test_tsv_line_spanning_two_columns_is_split_at_word_gap():
    tsv = ("level\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "5\t1\t1\t1\t0\t0\t50\t10\t95\t合法合作社協會\n"
           "5\t1\t1\t1\t100\t0\t50\t10\t95\t直轄市縣市政府\n")
    result = service.parse_tsv(tsv, page=1, rect=fitz.Rect(0, 0, 200, 100), height=842, zoom=1)
    assert result[0].line != result[-1].line
    assert service._mixed_list_items("(2)依法成立之合法合作社、協會、職業。(6)直轄市政府、")
    assert not service._mixed_list_items("10.符合新住民基本法第二條第一項第一款")


def test_dark_panel_is_not_a_set_of_table_columns():
    with fitz.open() as doc:
        p = doc.new_page(width=595, height=842)
        p.draw_rect(fitz.Rect(70, 180, 585, 290), color=None, fill=(.3, .6, .6))
        p.insert_text((85, 200), "Insurance contract", color=(1, 1, 1))
        assert service._vertical_rules(p, fitz.Rect(75, 183, 580, 285)) == []


def test_region_ocr_failure_is_retried_and_only_completed_read_cached(monkeypatch):
    from services import persistent_cache
    cache, calls = {}, []
    monkeypatch.setattr(persistent_cache, "load_json", lambda _namespace, k: cache.get(k))
    monkeypatch.setattr(persistent_cache, "save_json", lambda _namespace, k, v: cache.__setitem__(k, v))

    def fake_run(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired("tesseract", 30)
        tsv = b"level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        return subprocess.CompletedProcess(args, 0, stdout=tsv, stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with fitz.open() as doc:
        p = doc.new_page(width=80, height=50)
        p.insert_text((10, 20), "24")
        kwargs = {"zoom": 3, "models": {}, "stats": {}}
        with pytest.raises(subprocess.TimeoutExpired):
            service._read(p, p.rect, **kwargs)
        assert cache == {}
        assert service._read(p, p.rect, **kwargs) == []
        assert service._read(p, p.rect, **kwargs) == []
    assert len(calls) == 2


def test_parallel_ocr_pair_keeps_pdf_rendering_on_caller_thread(monkeypatch):
    caller, render_threads, ocr_threads = threading.get_ident(), [], []
    original = service._raster

    def render(*args):
        render_threads.append(threading.get_ident())
        return original(*args)

    def read(_png, **kwargs):
        ocr_threads.append(threading.get_ident())
        return "level\tpage_num\tblock_num\tpar_num\tline_num\ttext\n", False

    monkeypatch.setattr(service, "_raster", render)
    monkeypatch.setattr(service, "_read_tsv", read)
    with fitz.open() as old, fitz.open() as new:
        a, b = old.new_page(width=80, height=50), new.new_page(width=80, height=50)
        assert service._read_pair(a, b, a.rect, zoom=2, models={}, stats={}) == [[], []]
    assert render_threads == [caller, caller]
    assert len(ocr_threads) == 2 and all(worker != caller for worker in ocr_threads)
