import { createContext, useContext, useState, useCallback } from 'react';

const JudgeGuideContext = createContext(null);

const STORAGE_KEY = 'handoffscope_guide_dismissed';

export function JudgeGuideProvider({ children }) {
  const [isOpen, setIsOpen] = useState(() => {
    try {
      return typeof window !== 'undefined' && localStorage.getItem(STORAGE_KEY) !== 'true';
    } catch {
      return false;
    }
  });

  const openGuide = useCallback(() => setIsOpen(true), []);
  const closeGuide = useCallback(() => setIsOpen(false), []);
  const toggleGuide = useCallback(() => setIsOpen((prev) => !prev), []);

  const dismissPermanently = useCallback(() => {
    try {
      if (typeof window !== 'undefined') {
        localStorage.setItem(STORAGE_KEY, 'true');
      }
    } catch {
      // ignore
    }
    setIsOpen(false);
  }, []);

  return (
    <JudgeGuideContext.Provider
      value={{
        isOpen,
        openGuide,
        closeGuide,
        toggleGuide,
        dismissPermanently,
        setIsOpen,
      }}
    >
      {children}
    </JudgeGuideContext.Provider>
  );
}

export function useJudgeGuide() {
  const ctx = useContext(JudgeGuideContext);
  if (!ctx) {
    return {
      isOpen: false,
      openGuide: () => {},
      closeGuide: () => {},
      toggleGuide: () => {},
      dismissPermanently: () => {},
      setIsOpen: () => {},
    };
  }
  return ctx;
}
