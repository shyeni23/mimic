import './SkeletonLoader.css';

export default function SkeletonLoader({ width = '100%', height = '20px', borderRadius, count = 1, className = '' }) {
  return (
    <div className={`skeleton-wrapper ${className}`}>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="skeleton-item"
          style={{ width, height, borderRadius: borderRadius || 'var(--radius-md)' }}
        />
      ))}
    </div>
  );
}

export function SkeletonCard() {
  return (
    <div className="skeleton-card">
      <div className="skeleton-item" style={{ width: '100%', height: '180px', borderRadius: 'var(--radius-lg)' }} />
      <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div className="skeleton-item" style={{ width: '70%', height: '16px' }} />
        <div className="skeleton-item" style={{ width: '50%', height: '14px' }} />
        <div className="skeleton-item" style={{ width: '30%', height: '20px' }} />
      </div>
    </div>
  );
}
