# Animation rollback

The owner reports that the animation disappeared after PR #107. Restore the previous production version first, then reverse that PR in Git. Preserve the original workspace and all application code outside that revert.

- [ ] Restore the preceding Vercel deployment.
- [ ] Revert merge cb0953e1 with mainline parent 1.
- [ ] Confirm web and backend match 02afcabf exactly.
- [ ] Run typecheck, unit tests and the previous browser acceptance suite.
- [ ] Merge the revert after CI and verify marufov.com.

Automated input coverage did not establish the owner's browser experience. Any future motion changes need an owner-device check before replacing this version.
