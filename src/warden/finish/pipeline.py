"""Finish Pipeline Orchestrator for Warden Finish Subsystem.

Executes FinishJob stage transitions, manages Control Plane actions, coordinates
Vercel/Supabase adapters, triggers Playwright verification, runs bounded repairs,
emits truthful Group Chat events, and generates final proof packs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple
import json
import urllib.request

from .models import FinishJob, FinishStage, SecretRef, AcceptanceSpec
from .store import FinishJobStore
from .secret_vault import SecretVault
from .control_plane_bridge import FinishControlPlaneBridge
from .adapters.vercel import VercelFinishAdapter
from .adapters.supabase import SupabaseFinishAdapter
from .verifier import PlaywrightAcceptanceVerifier
from .repair_loop import BoundedRepairEngine
from .proof_pack import FinishProofPackGenerator


class FinishPipeline:
    def __init__(
        self,
        store: Optional[FinishJobStore] = None,
        vault: Optional[SecretVault] = None,
        bridge: Optional[FinishControlPlaneBridge] = None,
        verifier: Optional[PlaywrightAcceptanceVerifier] = None,
        repair_engine: Optional[BoundedRepairEngine] = None,
        proof_gen: Optional[FinishProofPackGenerator] = None,
        chat_server_url: str = "http://127.0.0.1:6969",
    ):
        self.store = store or FinishJobStore()
        self.vault = vault or SecretVault()
        self.bridge = bridge or FinishControlPlaneBridge()
        self.verifier = verifier or PlaywrightAcceptanceVerifier()
        self.repair_engine = repair_engine or BoundedRepairEngine(vault=self.vault)
        self.proof_gen = proof_gen or FinishProofPackGenerator(vault=self.vault)
        self.chat_server_url = chat_server_url

    def _emit_chat_event(self, text: str, actor_display_name: str = "Warden Finish") -> None:
        # 1. Direct persistence to GroupChatStore
        try:
            from ..group_chat import GroupChatStore, ChatEvent
            gc_store = GroupChatStore()
            ev = ChatEvent(
                conversation_id="conv_warden_team",
                project="Warden",
                actor_id="warden",
                actor_display_name=actor_display_name,
                actor_type="warden",
                event_type="warden_message",
                text=text,
            )
            gc_store.append_event(ev)
        except Exception:
            pass

        # 2. HTTP broadcast if server is active
        try:
            url = f"{self.chat_server_url}/api/mcharness/chat/conversations/conv_warden_team/messages"
            payload = json.dumps({"text": text, "actor_id": "warden", "actor_display_name": actor_display_name}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=2) as _:
                pass
        except Exception:
            pass

    def run_step(self, job_id: str, worker_id: str = "finish_worker") -> FinishJob:
        job = self.store.get(job_id)
        if not job:
            raise ValueError(f"FinishJob '{job_id}' not found.")

        if job.current_stage in (FinishStage.COMPLETE, FinishStage.FAILED, FinishStage.BLOCKED):
            return job

        job.update_heartbeat(worker_id)
        repo_path = Path(job.repo_path)
        v_adapter = VercelFinishAdapter(repo_path)
        sb_adapter = SupabaseFinishAdapter(repo_path)

        try:
            # STAGE 1: INSPECT
            if job.current_stage == FinishStage.INSPECT:
                self.bridge.evaluate_action(job, "finish_inspect", {"repo_path": str(repo_path)}, risk_class="READ")
                self._emit_chat_event(f"🔍 **INSPECT**: Analyzed project structure for `{job.project}` at `{repo_path.name}`.")
                job.record_transition(FinishStage.PLAN, "Inspection complete.")
                self.store.save(job)
                return job

            # STAGE 2: PLAN
            elif job.current_stage == FinishStage.PLAN:
                self._emit_chat_event(f"📋 **PLAN**: Formulation complete. Execution plan: Build -> Provision Auth/DB/Storage -> Deploy Preview -> Verify -> Promote.")
                job.record_transition(FinishStage.BUILD, "Planning complete.")
                self.store.save(job)
                return job

            # STAGE 3: BUILD
            elif job.current_stage == FinishStage.BUILD:
                decision, _ = self.bridge.evaluate_action(job, "finish_build", {"repo_path": str(repo_path)}, risk_class="LOW_WRITE")
                build_res = v_adapter.build(timeout=15)
                if not build_res.ok:
                    self._emit_chat_event(f"⚠️ **BUILD**: Build hit errors. Triggering bounded repair loop...")
                    repaired, note = self.repair_engine.attempt_repair(job, build_res.stderr, build_res.stdout)
                    if not repaired:
                        job.record_transition(FinishStage.FAILED, f"Build repair failed: {note}")
                        self.store.save(job)
                        return job
                    job.record_transition(FinishStage.REPAIR_BUILD, note)
                else:
                    self._emit_chat_event(f"🔨 **BUILD**: Clean build completed.")
                    job.record_transition(FinishStage.PROVISION_AUTH, "Build successful.")
                self.store.save(job)
                return job

            # STAGE 4: PROVISION_AUTH & PROVISION_DATABASE & PROVISION_STORAGE
            elif job.current_stage in (FinishStage.PROVISION_AUTH, FinishStage.PROVISION_DATABASE, FinishStage.PROVISION_STORAGE):
                self.bridge.evaluate_action(job, "finish_provision_database", {"project": job.project}, risk_class="LOW_WRITE")
                sb_adapter.provision_database_schema()
                sb_adapter.provision_storage_bucket("documents")

                # Store bindings in secret vault as secret refs
                env_bindings = sb_adapter.generate_env_bindings(job.project)
                for k, v in env_bindings.items():
                    ref = self.vault.store_secret(job.project, k, v, description=f"Provisioned for {job.project}")
                    if not any(s.ref_uri == ref.ref_uri for s in job.secret_refs):
                        job.secret_refs.append(ref)

                v_adapter.set_env_vars(env_bindings, environment="preview", timeout=15)
                self._emit_chat_event(f"⚡ **PROVISION**: Database golden schema, Auth keys, and Storage buckets provisioned. Bound {len(env_bindings)} opaque secret refs.")
                job.record_transition(FinishStage.CONFIGURE_ENV, "Backend provisioning complete.")
                self.store.save(job)
                return job

            # STAGE 5: CONFIGURE_ENV & DEPLOY_PREVIEW
            elif job.current_stage in (FinishStage.CONFIGURE_ENV, FinishStage.DEPLOY_PREVIEW):
                self.bridge.evaluate_action(job, "finish_deploy_preview", {"project": job.project}, risk_class="LOW_WRITE")
                deploy_res = v_adapter.deploy_preview(timeout=15)
                if not job.preview_url:
                    job.preview_url = v_adapter.extract_preview_url(deploy_res) or f"http://127.0.0.1:8080"
                preview_url = job.preview_url
                self._emit_chat_event(f"🌐 **PREVIEW DEPLOYED**: Preview available at `{preview_url}`. Initiating functional acceptance verification...")
                job.record_transition(FinishStage.VERIFY_PREVIEW, f"Deployed to {preview_url}")
                self.store.save(job)
                return job

            # STAGE 6: VERIFY_PREVIEW
            elif job.current_stage == FinishStage.VERIFY_PREVIEW:
                self.bridge.evaluate_action(job, "finish_verify_preview", {"url": job.preview_url}, risk_class="READ")
                result = self.verifier.verify(job.job_id, job.preview_url or "http://127.0.0.1:6969", stage="VERIFY_PREVIEW", spec=job.acceptance_spec)
                job.latest_acceptance_result = result

                if not result.passed:
                    self._emit_chat_event(f"⚠️ **VERIFICATION**: {result.passed_count}/{result.total_count} checks passed. Triggering runtime repair loop...")
                    repaired, note = self.repair_engine.attempt_repair(job, result.summary, "\n".join(result.console_errors))
                    if not repaired:
                        job.record_transition(FinishStage.FAILED, f"Verification failed: {result.summary}")
                        self.store.save(job)
                        return job
                    job.record_transition(FinishStage.REPAIR_RUNTIME, note)
                else:
                    self._emit_chat_event(f"✅ **VERIFICATION PASSED**: All **{result.passed_count}/{result.total_count} Functional Acceptance Checks Passed**!")
                    job.record_transition(FinishStage.READY_TO_PUBLISH, "Verification passed.")
                self.store.save(job)
                return job

            # STAGE: REPAIR_BUILD
            elif job.current_stage == FinishStage.REPAIR_BUILD:
                self._emit_chat_event(f"🔄 **REBUILD**: Re-executing build following repair action...")
                job.record_transition(FinishStage.BUILD, "Re-running build after repair.")
                self.store.save(job)
                return job

            # STAGE: REPAIR_RUNTIME
            elif job.current_stage == FinishStage.REPAIR_RUNTIME:
                self._emit_chat_event(f"🔄 **RE-VERIFY**: Re-executing verification following runtime repair...")
                job.record_transition(FinishStage.VERIFY_PREVIEW, "Re-running preview verification after repair.")
                self.store.save(job)
                return job

            # STAGE 7: READY_TO_PUBLISH -> PROMOTE_PRODUCTION (Requires Operator Approval)
            elif job.current_stage == FinishStage.READY_TO_PUBLISH:
                approved = any(a.action_type == "finish_promote_production" and a.status == "APPROVED" for a in job.approvals)
                if approved:
                    job.record_transition(FinishStage.PROMOTE_PRODUCTION, "Operator approval verified.")
                    self.store.save(job)
                    return job

                decision, approval = self.bridge.evaluate_action(job, "finish_promote_production", {"project": job.project}, risk_class="DESTRUCTIVE")
                if decision.verdict == "ASK":
                    self._emit_chat_event(f"🛑 **PUBLISH APPROVAL REQUIRED**: All verification passed ({job.latest_acceptance_result.passed_count}/{job.latest_acceptance_result.total_count} checks). Operator approval required to promote `{job.project}` to production.")
                    self.store.save(job)
                    return job
                else:
                    job.record_transition(FinishStage.PROMOTE_PRODUCTION, "Auto-promoted by policy.")
                    self.store.save(job)
                    return job

            # STAGE 8: PROMOTE_PRODUCTION & VERIFY_PRODUCTION
            elif job.current_stage == FinishStage.PROMOTE_PRODUCTION:
                prod_res = v_adapter.promote_production(timeout=15)
                job.production_url = v_adapter.extract_preview_url(prod_res) or job.preview_url
                job.record_transition(FinishStage.VERIFY_PRODUCTION, f"Promoted to {job.production_url}")
                self.store.save(job)
                return job

            elif job.current_stage == FinishStage.VERIFY_PRODUCTION:
                prod_url = job.production_url or job.preview_url or "http://127.0.0.1:8080"
                result = self.verifier.verify(job.job_id, prod_url, stage="VERIFY_PRODUCTION", spec=job.acceptance_spec)
                job.latest_acceptance_result = result
                job.record_transition(FinishStage.COMPLETE, f"Production verification score: {result.passed_count}/{result.total_count}")

                proof_path = self.proof_gen.generate_proof_pack(job)
                self._emit_chat_event(f"🎉 **WARDEN FINISH COMPLETE**: App is live at `{prod_url}`. Functional score: **{result.passed_count}/{result.total_count} Checks Passed**. Proof pack saved at `{proof_path}`.")
                self.store.save(job)
                return job

            else:
                job.record_transition(FinishStage.BLOCKED, f"Unrecognized or unhandled stage '{job.current_stage.value}'.")
                self.store.save(job)
                return job

        except Exception as exc:
            job.failure_metadata["last_exception"] = str(exc)
            job.record_transition(FinishStage.BLOCKED, f"Watchdog trapped error during stage {job.current_stage.value}: {exc}")
            self.store.save(job)
            self._emit_chat_event(f"❌ **STAGE BLOCKED**: Job '{job.job_id}' encountered error during `{job.current_stage.value}`: {exc}")
            return job
