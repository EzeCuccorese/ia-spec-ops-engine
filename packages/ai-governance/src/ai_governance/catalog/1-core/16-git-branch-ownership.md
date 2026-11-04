# Git Branch Ownership

## Invariants
- **Ownership Definition**: A branch is the user's only if the user created it or asked the agent to create it. Unclear ownership means not the user's.
- **Protected Actions on Non-Owned Branches**: On any other branch (`main`, default, shared, or other people's branches), the agent never pushes, force-pushes, rebases, resets, deletes or commits without first showing the exact action and branch and getting the user's explicit authorization.
- **Single-Action Authorization**: One authorization covers one action on one branch.
