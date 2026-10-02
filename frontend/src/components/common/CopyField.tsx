import React, { useState, useCallback } from 'react';
import { Copy, Check } from 'lucide-react';

interface CopyFieldProps {
  value: string;
  label?: string;
  shorten?: boolean;
  truncateLength?: number;
  className?: string;
}

export const CopyField: React.FC<CopyFieldProps> = ({
  value,
  label,
  shorten = false,
  truncateLength = 8,
  className = '',
}) => {
  const [copied, setCopied] = useState(false);

  const displayValue = shorten && value.length > truncateLength * 2 + 2
    ? `${value.slice(0, truncateLength)}…${value.slice(-truncateLength)}`
    : value;

  const handleCopy = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
      const input = document.createElement('textarea');
      input.value = value;
      document.body.appendChild(input);
      input.select();
      document.execCommand('copy');
      document.body.removeChild(input);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [value]);

  return (
    <span 
      className={`inline-flex items-center gap-1.5 font-mono text-xs text-[var(--color-text-primary)] ${className}`}
      title={label ? `${label}: ${value}` : value}
    >
      <span className="select-all" aria-label={label || 'Identifier'}>
        {displayValue}
      </span>
      <button
        type="button"
        onClick={handleCopy}
        className="btn-icon text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
        aria-label={copied ? `Copied ${label || 'value'}` : `Copy ${label || 'value'}`}
        title="Copy exact identifier"
      >
        {copied ? (
          <Check size={13} className="text-[var(--color-accepted)]" aria-hidden="true" />
        ) : (
          <Copy size={13} aria-hidden="true" />
        )}
      </button>
      {copied && (
        <span className="sr-only" role="status">Copied to clipboard</span>
      )}
    </span>
  );
};
