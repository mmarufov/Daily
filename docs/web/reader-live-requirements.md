# Live web Reader requirements

The public Reader presents frozen editions for evaluation fixtures. Its recording date, source identifiers and synthetic-story labels describe those saved inputs.

A future live web Reader needs the following integration work. These are implementation requirements moved from the Reader page on November 5, 2026; they are not a verification of current production configuration.

- **Browser access:** configure and verify the intended web origin in `CORS_ORIGINS` before calling the backend from a browser.
- **Web sign-in:** register a web OAuth client for the deployed origin and confirm that `POST /auth/google` accepts its intended audience. Recheck the current backend contract instead of reusing an iOS client assumption.
- **Feedback identifiers:** preserve `feed_request_id`, `reader_generation` and `delivery_position` from the actual live delivery when submitting feedback.
- **End-to-end verification:** test sign-in, edition delivery, article opening and feedback against the deployed services before describing the web Reader as live.

These requirements do not change the recorded Reader, its profile links or the Lab runner.
