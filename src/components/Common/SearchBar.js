import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { RiSearchLine, RiCloseLine } from 'react-icons/ri';
import './SearchBar.css';

export default function SearchBar({ placeholder = 'Search...', onSearch }) {
  const [query, setQuery] = useState('');
  const [isFocused, setIsFocused] = useState(false);

  const handleChange = (e) => {
    setQuery(e.target.value);
    onSearch?.(e.target.value);
  };

  const clear = () => {
    setQuery('');
    onSearch?.('');
  };

  return (
    <motion.div
      className={`search-bar ${isFocused ? 'focused' : ''}`}
      animate={{ boxShadow: isFocused ? '0 0 20px rgba(108, 99, 255, 0.2)' : 'none' }}
    >
      <RiSearchLine className="search-icon" />
      <input
        type="text"
        value={query}
        onChange={handleChange}
        onFocus={() => setIsFocused(true)}
        onBlur={() => setIsFocused(false)}
        placeholder={placeholder}
      />
      <AnimatePresence>
        {query && (
          <motion.button
            className="search-clear"
            onClick={clear}
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.8 }}
          >
            <RiCloseLine />
          </motion.button>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
