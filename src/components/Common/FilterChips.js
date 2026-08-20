import { motion } from 'framer-motion';
import './FilterChips.css';

export default function FilterChips({ filters, activeFilter, onSelect }) {
  return (
    <div className="filter-chips">
      {filters.map((filter) => (
        <motion.button
          key={filter}
          className={`filter-chip ${activeFilter === filter ? 'active' : ''}`}
          onClick={() => onSelect(filter)}
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          layout
        >
          {activeFilter === filter && (
            <motion.span
              className="chip-bg"
              layoutId="activeChip"
              transition={{ type: 'spring', stiffness: 500, damping: 30 }}
            />
          )}
          <span className="chip-label">{filter}</span>
        </motion.button>
      ))}
    </div>
  );
}
