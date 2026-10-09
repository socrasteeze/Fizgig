# Web UI review

Fixes for the confirmed findings. Counts: 82 fixed, 0 won't fix, 0 disputed.

Default suite, three times, each 156 tests and 3 skipped, all OK: 205.785s, 208.874s, 206.484s. Golden: 3 tests OK, 11.591s. `npm --prefix webui run build` passed after `webui/src/api.d.ts` was regenerated. `checks\check_appearance.py` passed.

| # | Status | Change | Test |
|---|---|---|---|
| 1 | fixed | Engine events keep a sequence and a per-stream cursor. Reading does not clear the list. | `test_events_since_does_not_consume`, `test_engine_events_reach_every_stream` |
| 2 | fixed | A blank model path is filled from Preferences before launch. | `test_blank_context_uses_preferences`, `test_prefs_fill_empty_context_matches_desktop` |
| 3 | fixed | The host assigns every render gen. A stale or failed reply is an error, and busy is cleared. | `test_stale_render_raises`, `test_newest_gen_wins` |
| 4 | fixed | Same broadcast as 1. The page stream no longer consumes engine events. | `test_engine_events_reach_every_stream` |
| 5 | fixed | Bake and Explorer save call the loaded engine's `save_repaired`. The file baker is only a fallback, and Z-Image, Qwen, and SDXL are refused when it cannot map them. | `test_bake_uses_loaded_engine`, `test_save_uses_loaded_engine`, `test_bake_refuses_unmapped_family` |
| 6 | fixed | Same broadcast as 1, so a second EventSource still receives `done` and frames. | `test_events_since_does_not_consume` |
| 7 | fixed | Finished jobs use the stored step, total, and loss. They do not reread the log. | `test_finished_job_does_not_reread_its_log` |
| 8 | fixed | Client training paths are resolved inside the configured roots before a plan is built. A job output widens download roots only when it is already inside one. | `test_launch_paths_stay_inside_roots` |
| 9 | fixed | A repair preset name is sanitized, then the file must stay inside the preset directory. | `test_read_preset_stays_in_the_preset_dir` |
| 10 | fixed | UNC and device paths are rejected before any stat. Containment is checked lexically, then the path is resolved. Short and long Windows names of a root both count. | `test_unc_device_names_case_and_zip_junk` |
| 11 | fixed | An active job parses only new log bytes. The SSE round runs off the event loop. | `test_active_log_parses_only_new_bytes` |
| 12 | fixed | A device is armed only when a job in this observe call changes from queued or running to done. A later add does not start by itself. | `test_one_shot_ready_does_not_start_a_later_add`, `test_already_done_job_does_not_start_the_queue` |
| 13 | fixed | Pause with no state dir writes a failed job. The state dir is matched on the tidied name. | `test_pause_records_tidied_name_or_failure` |
| 14 | fixed | The desktop lock index comes from the CUDA env the run will actually get, including a UUID mapped through the GPU list. | `test_desktop_lock_uses_the_chosen_card` |
| 15 | fixed | A failed engine load unloads the engine before the GPU lock is released. | `test_failed_load_unloads_before_unlock` |
| 16 | fixed | Same index as 14. Web launches set `CUDA_DEVICE_ORDER=PCI_BUS_ID`. | `test_desktop_lock_uses_the_chosen_card`, `test_two_devices_run_together` |
| 17 | fixed | `.pause_requested` pauses only when the Training stage exits. A cache exit leaves the flag. | `test_pause_flag_survives_a_cache_stage` |
| 18 | fixed | An imported item with no model paths uses Preferences at launch, the same fill as 2. | `test_blank_context_uses_preferences` |
| 19 | fixed | A blank cache folder uses the Preferences cache directory. | `test_blank_context_uses_preferences` |
| 20 | fixed | A blank captioner, trigger, and instruction set are filled from Preferences. The placeholder `trigger_word` is ignored. | `test_blank_context_uses_preferences`, `test_caption_trigger_is_saved_and_other_keys_stay` |
| 21 | fixed | Opening a family seeds the first built-in preset. The optimizer fallback is `adamw8bit`. | `test_optimizer_catalog_and_area_pins` |
| 22 | fixed | Changing Model Area, except Custom, rewrites the timestep window. | `test_optimizer_catalog_and_area_pins` |
| 23 | fixed | Advanced flags are disabled and labelled as reference. They are not sent. | `test_page_presets_advanced_and_controls` |
| 24 | fixed | Invalid numbers stay as text so the launch checks refuse them. | `test_invalid_numbers_stay_raw` |
| 25 | fixed | A preset chip merges only its own keys and kind. | `test_preset_overlay_keeps_kind` |
| 26 | fixed | Optimizer choices are the catalog, read without importing torch. | `test_optimizer_catalog_and_area_pins` |
| 27 | fixed | Load and unload report the worker gen, and the host catches `latest` up. A stale render clears busy. | `test_newest_gen_wins`, `test_stale_render_raises` |
| 28 | fixed | A render cancelled by load or unload clears busy when nothing newer is pending. | `test_stale_render_raises` |
| 29 | fixed | The profiler view returns a stored result first, and `failed` when the run ended without one. | `test_engine_view_stored_before_running_and_failed_when_idle` |
| 30 | fixed | Repair edits update a draft ref before the debounced render. | `test_page_presets_advanced_and_controls` |
| 31 | fixed | Panels use the gen the server returns instead of a counter that restarts at 0. | `test_newest_gen_wins` |
| 32 | fixed | The Training tab prefills model paths from `/api/prefs`. The server fill in 2 still applies when they are blank. | `test_page_presets_advanced_and_controls` |
| 33 | fixed | Pause, resume, and stop show the server's detail, problems, and warning confirm. | `test_page_presets_advanced_and_controls` |
| 34 | fixed | Metadata Save sends `extra` only after Load of that same path. | `test_page_presets_advanced_and_controls` |
| 35 | fixed | Saving a repair preset refreshes the name list and leaves the sliders alone. | `test_page_presets_advanced_and_controls` |
| 36 | fixed | The profiler reads `/api/profile/engine` on mount and shows running, failed, and done. | `test_page_presets_advanced_and_controls` |
| 37 | fixed | The entrypoint waits on `tailscale status --json`, then runs `tailscale up`. The test stub fails `status` until `up`. | `test_starts_with_auth_key` |
| 38 | fixed | The web image copies `lora_trainer_gui.py` and sets the prefs file and roots under `/workspace`. | `test_image_copies_serve_prefs_and_fs` |
| 39 | fixed | A lifespan thread calls `observe` while the server is running. GET `/api/jobs` and the event stream do not. | `test_auto_advance`, `test_queue_advances_per_device` |
| 40 | fixed | Repair checks `ref_image_path` against the roots. An empty path is cleared. | `test_render_checks_reference_root` |
| 41 | fixed | A converter name cannot carry a drive prefix or reserved characters, and the file stays in the output folder. | `test_output_name_cannot_escape` |
| 42 | fixed | A bake name uses the same leaf rule, and the destination stays in the output folder. | `test_bake_rejects_bad_output_name` |
| 43 | fixed | A Royale export picks a free name unless overwrite is set. | `test_export_command_and_file` |
| 44 | fixed | On Windows, upload names that differ only by case count as the same file. | `test_unc_device_names_case_and_zip_junk` |
| 45 | fixed | Upload and preset names reject reserved DOS device stems. | `test_unc_device_names_case_and_zip_junk`, `test_read_preset_stays_in_the_preset_dir` |
| 46 | fixed | A Gizmo source upload returns 409 unless overwrite is set. | `test_upload_conflicts_unless_overwrite` |
| 47 | fixed | The entrypoint exports the tailnet host from `Self.DNSName` with the trailing dot removed. The server strips that dot too. | `test_starts_with_auth_key`, `test_keeps_configured_tailnet_host`, `test_tailnet_host_ignores_a_trailing_dot` |
| 48 | fixed | Sample URLs percent-encode the file name. | `test_samples_keep_this_lora_and_the_latest` |
| 49 | fixed | Origin must match scheme, host, and port. Another localhost port is rejected. | `test_origin_must_match_scheme_host_and_port` |
| 50 | fixed | A bare `FAIL:` line after RUN quits the caption worker and fails the job. | `test_defaults_follow_prefs_and_a_fail_line_ends_the_job` |
| 51 | fixed | Workbench GPU checks use the engine device, not device 0. | `test_gpu_free_uses_engine_device` |
| 52 | fixed | Changing the engine device is refused while a request is in flight, and waiters are woken if the process is stopped. | `test_set_device_refuses_while_a_request_is_in_flight` |
| 53 | fixed | The idle timer restarts when a load finishes and when the latest render reaches a terminal event. | `test_long_load_and_render_are_not_idle_immediately` |
| 54 | fixed | Replacing `queue.json` retries `PermissionError`. | `test_queue_write_retries_permission_error` |
| 55 | fixed | A failed spawn marks the job failed. A queued pid of 0 older than a short grace is failed on reconcile. | `test_spawn_failure_and_stale_queue_are_failed` |
| 56 | fixed | Same idle-timer restart as 53. | `test_long_load_and_render_are_not_idle_immediately` |
| 57 | fixed | Qwen caption defaults follow the saved training instruction, 120 tokens, and Qwen when its file exists. | `test_defaults_follow_prefs_and_a_fail_line_ends_the_job` |
| 58 | fixed | A render that does not stop is killed with the worker. The lock is not released under a live render. | `test_stuck_render_is_not_unloaded` |
| 59 | fixed | A new engine session removes unused session folders, and preview files older than the latest few gens are dropped. | `test_spawn_drops_old_sessions_and_sets_pci_order`, `test_old_preview_files_are_dropped` |
| 60 | fixed | The extra `clear_cancel` inside repair and RefMod paint is gone. The worker loop still clears, then rechecks the gen. | none separate; the loop recheck is in `engine_host.py` |
| 61 | fixed | A cancelled Explorer roll is `Cancelled`, not an engine error. | `test_cancelled_preview_is_not_an_engine_failure` |
| 62 | fixed | A repair clip file uses the worker gen, and the frames folder is cleared first. | `test_repair_clip_uses_worker_gen` |
| 63 | fixed | A closed EventSource reconnects after about 2 seconds and refetches jobs. | `test_page_presets_advanced_and_controls` |
| 64 | fixed | Log, sample, and profiler polls schedule the next tick after a failed fetch. | `test_page_presets_advanced_and_controls` |
| 65 | fixed | Sample lists keep this LoRA's files, at most the latest 48, and images load lazily. | `test_samples_keep_this_lora_and_the_latest`, `test_page_presets_advanced_and_controls` |
| 66 | fixed | Same read-only Advanced section as 23. | `test_page_presets_advanced_and_controls` |
| 67 | fixed | A choice value missing from the list is shown as its own option. The submitted value is unchanged. | `test_optimizer_catalog_and_area_pins` |
| 68 | fixed | Repair treats 0 as a real seed and strength. | `test_page_presets_advanced_and_controls` |
| 69 | fixed | Browser notifications catch a throw and fall back to `showNotification`. | `test_page_presets_advanced_and_controls` |
| 70 | fixed | Changing the Repair family disarms the engine and clears the preview until Load. | `test_page_presets_advanced_and_controls` |
| 71 | fixed | Gizmo polls until the job is done, failed, or stopped. | `test_page_presets_advanced_and_controls` |
| 72 | fixed | Bad job JSON is corrupt immediately, can be deleted, and writes are fsynced before replace. | `test_corrupt_record_can_be_deleted` |
| 73 | fixed | Saving preferences refuses when `prefs.json` cannot be parsed, and does not overwrite it. | `test_corrupt_prefs_are_not_replaced` |
| 74 | fixed | A failed progress write is skipped. The trainer is still waited on or killed before the lock is released. | `test_status_write_does_not_kill_the_trainer` |
| 75 | fixed | Deleting a record removes `job.json` last and retries a sharing violation. A corrupt record can still be deleted. | `test_corrupt_record_can_be_deleted` |
| 76 | fixed | A log response is at most 256KB. A negative offset is the tail. History asks for that tail. | `test_log_is_capped_and_tail_is_marked` |
| 77 | fixed | Zip members under `__MACOSX/` and AppleDouble `._*` leaves are skipped. | `test_unc_device_names_case_and_zip_junk` |
| 78 | fixed | Same tailnet-host export as 47, and the Docker section of the user guide names the variable. | `test_keeps_configured_tailnet_host`, `test_docs_and_api_scripts` |
| 79 | fixed | The API scripts try `FIZGIG_PY`, then both venv layouts, then `python3`, then `python`. | `test_docs_and_api_scripts` |
| 80 | fixed | The pause test waits until the runner pid is dead. A daemon thread reaps the detached runner. | `test_pause_resume_and_stop` |
| 81 | fixed | The user guide shows `set`, `$env:`, and `export` for the tailnet host. | `test_docs_and_api_scripts` |
| 82 | fixed | First run includes `requirements-web.txt` and `npm --prefix webui ci`. | `test_docs_and_api_scripts` |

## Rounds 2 and 3

A re-check of the 39 high and medium findings confirmed 37 fixed and found 22 regressions introduced by the fixes. Round 2 (commit 427e604) fixed those plus the two partial fixes, added tests for findings 22, 23, 27 and 28, and isolated job-starting tests (`checks/runner_guard.py`). A second re-check confirmed 22 of 24 and found one medium regression (Training-tab model edits lost on tab switch) and three low ones. Round 3 (commit d299c78) fixed them: caption FAIL lines are classified by the worker's real job-level lines, event streams resume by SSE id, client paths are confined lexically with no filesystem access, and Preferences-filled paths are trusted.
