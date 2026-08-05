# Deploy conflict test fixture

Temporary. Exists only to prove that `deploy.yml`'s `git apply --3way` failure
path aborts BEFORE any `systemctl restart` (commit 4bee161, which had never
executed). Deleted once D3 and D2 pass.

Nothing imports this file. It has no runtime role.

STATE: baseline
