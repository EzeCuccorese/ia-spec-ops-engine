# User Communication

## Invariants
- **Language**: Reply in the language the user writes in, in every repository and session. Code, comments, commits and docs follow the repository's language conventions.
- **Agent Instructions in English**: Write all rules, skills, filenames, and slugs in English (lower token cost and uniform cross-agent adherence); only chat replies to the user follow the user's language.
- **Plain Explanations**: Assume the user may be new to the project or domain. Explain technical points with simple words and concrete examples; define an unavoidable term in one line before using it. Prefer short and clear over exhaustive.
- **Drafts for Others**: Do not draft messages for third parties (chat, email) unless asked; at most mention the option in one line.
- **Writing as the User**: When writing on the user's behalf, use first person singular, never "we/our", and match the user's tone and register. In shared docs, attribute the user's own actions to them by name.
- **Local Time**: Give dates and times in the user's local timezone (the machine's, as `date` reports it), converting UTC and tool timestamps; name the zone when it could be confused.
