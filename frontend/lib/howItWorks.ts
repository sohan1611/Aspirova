export const HOW_IT_WORKS_STORAGE_KEY = "aspirova.howItWorks.dismissed";

export function isHowItWorksDismissed(storage: Pick<Storage, "getItem">): boolean {
  try {
    return storage.getItem(HOW_IT_WORKS_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

// Runs in the document head before the strip can paint.
export const HOW_IT_WORKS_DISMISSED_SCRIPT = `(function(){try{if(localStorage.getItem(${JSON.stringify(HOW_IT_WORKS_STORAGE_KEY)})==="1"){document.documentElement.setAttribute("data-hiw-dismissed","");}}catch(e){}})();`;
