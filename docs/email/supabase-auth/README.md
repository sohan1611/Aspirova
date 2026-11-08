# Supabase Auth email templates

Paste each HTML file into Supabase under Authentication → Emails → Templates.
The files use the Aspirova shared transactional shell and the fixed public site
https://www.aspirova.org for the logo and footer links.

| File | Dashboard template | Suggested subject |
| --- | --- | --- |
| confirm-signup.html | Confirm signup | Confirm your email |
| reset-password.html | Reset password | Reset your password |
| magic-link.html | Magic link | Your sign-in link |
| change-email.html | Change email address | Confirm your new email |

If a current template uses a custom link, such as a token_hash flow, keep that
link in both the button and fallback text instead of replacing it with
{{ .ConfirmationURL }}. Preserve the current authentication redirect behaviour.
These are dashboard handover files. The preview script only writes files.
