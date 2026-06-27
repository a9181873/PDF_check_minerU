export function getTrimmedDiffText(oldValue: string, newValue: string): string {
  let prefixLength = 0;
  while (
    prefixLength < oldValue.length &&
    prefixLength < newValue.length &&
    oldValue[prefixLength] === newValue[prefixLength]
  ) {
    prefixLength += 1;
  }

  let suffixLength = 0;
  while (
    suffixLength + prefixLength < oldValue.length &&
    suffixLength + prefixLength < newValue.length &&
    oldValue[oldValue.length - 1 - suffixLength] === newValue[newValue.length - 1 - suffixLength]
  ) {
    suffixLength += 1;
  }

  const trimText = (value: string) => {
    if (prefixLength + suffixLength >= value.length) return value.trim();
    return value.slice(prefixLength, value.length - suffixLength).trim();
  };

  const oldSnippet = trimText(oldValue);
  const newSnippet = trimText(newValue);
  if (!oldSnippet && !newSnippet) {
    return `${oldValue} → ${newValue}`;
  }
  return `${oldSnippet || '[刪除]'} → ${newSnippet || '[新增]'}`;
}
