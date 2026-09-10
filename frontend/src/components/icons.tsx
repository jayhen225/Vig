export const Logo = ({ size = 26 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    <path d="M4 5l8 15 8-15" stroke="#35e08a" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const Search = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
    <circle cx="11" cy="11" r="7" stroke="#565f6d" strokeWidth="2" />
    <path d="M20 20l-3.5-3.5" stroke="#565f6d" strokeWidth="2" strokeLinecap="round" />
  </svg>
);

export const Plus = ({ stroke = "#35e08a", size = 15 }: { stroke?: string; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    <path d="M12 5v14M5 12h14" stroke={stroke} strokeWidth="2.4" strokeLinecap="round" />
  </svg>
);

export const Close = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
    <path d="M6 6l12 12M18 6L6 18" stroke="#565f6d" strokeWidth="2" strokeLinecap="round" />
  </svg>
);

export const Chevron = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
    <path d="M6 9l6 6 6-6" stroke="#8a93a0" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
