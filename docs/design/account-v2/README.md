# Account v2: before and after

Screenshots for the `/account` redesign. Each one is a full page (footer cropped off) from a production build, signed in as a fictional test user against a throwaway local database.

- `before/` is master at 3dcd328; `after/` is `feat/account-redesign`.
- Names follow `<section>-<width>-<theme>.png`, for example `notifications-390-dark.png`.
- Sections: `profile`, `resume`, `subscription`, `notifications`, `saved`, `security`.
- Extra states:
  - `free-subscription` and `free-notifications`: the Free plan, with locked rows and the 1-company limit reached.
  - `cancelling-subscription`: a paid plan set to cancel at the end of its period.
- Dark shots add the `.dark` class by hand. Production forces the light theme (`forcedTheme="light"` in `app/layout.tsx`), so these only check that the tokens hold up if dark mode is turned on.
- The fixed bottom tab bar is hidden in the 390px shots. A full-page capture would otherwise draw it in the middle of the page.
