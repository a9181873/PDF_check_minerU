import React from 'react';
import { CheckCircle, File, Upload } from 'lucide-react';

interface FileUploadAreaProps {
  side: 'old' | 'new';
  label: string;
  file: File | null;
  isDragging: boolean;
  isUploading: boolean;
  onDrop: (event: React.DragEvent<HTMLDivElement>, side: 'old' | 'new') => void;
  onDragOver: (event: React.DragEvent<HTMLDivElement>) => void;
  onDragLeave: (event: React.DragEvent<HTMLDivElement>) => void;
  onFileSelect: (side: 'old' | 'new', files: FileList | null) => void;
  onRemove: (side: 'old' | 'new') => void;
}

export default function FileUploadArea({
  side,
  label,
  file,
  isDragging,
  isUploading,
  onDrop,
  onDragOver,
  onDragLeave,
  onFileSelect,
  onRemove,
}: FileUploadAreaProps) {
  return (
    <div
      onDrop={(event) => onDrop(event, side)}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      className={`relative border-2 border-dashed rounded-xl p-8 text-center transition-all ${
        isDragging ? 'border-primary-500 bg-primary-50' : 'border-gray-300 hover:border-gray-400 hover:bg-gray-50'
      }`}
    >
      <input
        type="file"
        id={`${side}-upload`}
        className="hidden"
        accept=".pdf"
        onChange={(event) => onFileSelect(side, event.target.files)}
        disabled={isUploading}
      />

      {file ? (
        <div className="space-y-4">
          <div className="flex items-center justify-center">
            <div className="p-3 bg-green-100 rounded-full">
              <CheckCircle className="text-green-600" size={32} />
            </div>
          </div>
          <div>
            <h3 className="font-medium text-gray-900 mb-1">{label} 已選擇</h3>
            <div className="flex items-center justify-center space-x-2 text-gray-600">
              <File size={16} />
              <span className="text-sm truncate max-w-xs">{file.name}</span>
            </div>
            <p className="text-sm text-gray-500 mt-1">
              {(file.size / 1024 / 1024).toFixed(2)} MB
            </p>
          </div>
          <button
            type="button"
            onClick={() => onRemove(side)}
            className="px-4 py-2 text-sm bg-red-100 text-red-700 rounded-lg hover:bg-red-200 transition-colors"
            disabled={isUploading}
          >
            移除檔案
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-center">
            <div className="p-3 bg-gray-100 rounded-full">
              <Upload className="text-gray-400" size={32} />
            </div>
          </div>
          <div>
            <h3 className="font-medium text-gray-900 mb-1">{label}</h3>
            <p className="text-gray-600">拖放 PDF 檔案到此處，或點擊選擇檔案</p>
          </div>
          <label
            htmlFor={`${side}-upload`}
            className={`inline-block px-6 py-3 rounded-lg font-medium transition-colors cursor-pointer ${
              isUploading
                ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                : 'bg-primary-600 text-white hover:bg-primary-700'
            }`}
          >
            選擇檔案
          </label>
        </div>
      )}
    </div>
  );
}
