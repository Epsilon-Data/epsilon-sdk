"""Project-scoped operations shared by the owned browser API."""
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from threading import RLock

from sdk import catalogue, credentials, llm, projects
from sdk.llm import pricing
from sdk.llm.base import LLMError
from sdk.client import APIClient
from sdk.workbench.errors import PublicError, NotFound
from sdk.errors import SDKError
from sdk.profile import ProfileError, profile_project
from sdk.project_setup import initialise_project
from sdk.workbench import analysis
from sdk.workbench.jobs import Jobs
from sdk.workbench.security import safe_metadata, safe_path
from sdk.workbench.display import artifact_view
from sdk.workbench.datasets import approved_datasets, dataset_details, require_approved
from sdk.workbench.store import Store, now


class Workbench:
    def __init__(self, launch_dir, state_dir=None, record=True):
        self.launch_dir = str(Path(launch_dir).resolve())
        self.state_dir = Path(state_dir or (Path(os.path.expanduser("~")) / ".epsilon_sdk"))
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.credentials_path = (self.state_dir / "credentials.ini" if state_dir is not None
                                 else credentials.credentials_path())
        self.store = Store(self.state_dir / "workbench.db")
        self.jobs = Jobs(self.store)
        self.lock = RLock()
        self.record = record
        self.memory_key = None
        self.ai_lock = RLock()
        self._ai_cache = None
        self._models_cache = None
        self.profiles = {}
        self.client_factory = APIClient
        self._register_launch()

    @contextmanager
    def registry(self):
        with self.lock:
            lock_path = self.state_dir / "projects.lock"
            with lock_path.open("a+") as lock_file:
                try:
                    import fcntl
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                except ImportError:
                    pass
                path = self.state_dir / "projects.json"
                try:
                    payload = json.loads(path.read_text()) if path.exists() else {"version": 1, "projects": []}
                except (ValueError, OSError):
                    raise PublicError("The project registry could not be read. Restore it before making changes.")
                if not isinstance(payload, dict) or not isinstance(payload.get("projects"), list):
                    raise PublicError("The project registry is invalid.")
                previous = json.dumps(payload, sort_keys=True)
                yield payload["projects"]
                if previous != json.dumps(payload, sort_keys=True):
                    fd, temporary = tempfile.mkstemp(prefix=".projects-", dir=str(self.state_dir))
                    try:
                        with os.fdopen(fd, "w") as stream:
                            json.dump(payload, stream, indent=2)
                        os.replace(temporary, str(path))
                    finally:
                        if os.path.exists(temporary):
                            os.unlink(temporary)

    def _register_launch(self):
        if projects.looks_like_project(self.launch_dir):
            with self.registry() as entries:
                if any(Path(p["path"]).resolve() == Path(self.launch_dir) for p in entries):
                    return
            self.create_project(Path(self.launch_dir).name, self.launch_dir, "")

    def project(self, project_id):
        with self.registry() as entries:
            project = next((dict(p) for p in entries if p["id"] == project_id), None)
        if project is None:
            raise NotFound("Project not found.")
        if Path(project["path"]).is_symlink():
            raise PublicError("The registered project folder is a symbolic link. Register its real location.")
        return project

    def project_list(self):
        with self.registry() as entries:
            items = [dict(p) for p in entries]
        for item in items:
            root = Path(item["path"])
            item["exists"] = root.is_dir()
            item["ready"] = ((root / "generated/data.csv").is_file() and
                             (root / "generated/archetype.json").is_file())
        return sorted(items, key=lambda p: p.get("opened", ""), reverse=True)

    def create_project(self, name, path, description, dataset_id=None):
        if dataset_id is not None:
            # Recheck access when the user confirms setup, before creating files.
            require_approved(self.client(), dataset_id)
        root = Path(path).expanduser().resolve()
        if root == Path(root.anchor) or root == Path(os.path.expanduser("~")) or root == self.state_dir.resolve() or self.state_dir.resolve() in root.parents:
            raise PublicError("Choose a research folder outside the SDK credentials directory.")
        if not name.strip():
            raise PublicError("Enter a project name.")
        with self.registry() as entries:
            if any(Path(p["path"]).resolve() == root for p in entries):
                raise PublicError("This folder is already registered as a project.")
            root.mkdir(parents=True, exist_ok=True)
            base = projects.slug(name)
            project_id, suffix = base, 2
            while any(p["id"] == project_id for p in entries):
                project_id, suffix = base + "-" + str(suffix), suffix + 1
            project = {"id": project_id, "name": name.strip(), "description": description.strip(),
                       "path": str(root), "created": now(), "opened": now()}
            if dataset_id is not None:
                project["dataset_id"] = dataset_id
            entries.append(project)
        return project

    def update_project(self, project_id, name, description):
        if not name.strip():
            raise PublicError("Enter a project name.")
        self.project(project_id)
        with self.registry() as entries:
            for project in entries:
                if project["id"] == project_id:
                    project.update(name=name.strip(), description=description.strip())
        return self.project(project_id)

    def profile(self, project_id):
        project = self.project(project_id)
        root = project["path"]
        paths = [safe_path(root, "generated/data.csv"), safe_path(root, "generated/archetype.json"),
                 safe_path(root, "project.yml", must_exist=False)]
        fingerprint = tuple((str(p), p.stat().st_dev, p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_ctime_ns, p.stat().st_size) for p in paths if p.exists())
        with self.lock:
            cached = self.profiles.get(project_id)
            if cached and cached[0] == fingerprint:
                return cached[1]
        profile = profile_project(root)
        with self.lock:
            self.profiles[project_id] = (fingerprint, profile)
        return profile

    def fields(self, project_id):
        """Schema field paths and types the assistant and checks may use."""
        return safe_metadata(self.profile(project_id))["fields"]

    def detail(self, project_id):
        project = self.project(project_id)
        try:
            profile = self.profile(project_id)
        except (ProfileError, SDKError):
            return dict(project, ready=False)
        # Browser metadata deliberately excludes measured categories/ranges.
        metadata = safe_metadata(profile)
        dataset = dict(metadata, title=profile.title, rows=profile.grain.rows,
                       archetype=profile.archetype_id, schema_hash=profile.schema_hash,
                       version=profile.dataset_version, min_cell=profile.min_cell,
                       caveats=profile.caveats, dataset_id=profile.dataset_id)
        return dict(project, ready=True, dataset=dataset, capabilities=self.capabilities(project_id),
                    usage=self.store.usage(project_id),
                    research_context=self.store.setting("research:" + project_id, {"goal": "", "fields": []}))

    def capabilities(self, project_id):
        result = []
        for match in catalogue.evaluate(self.profile(project_id)):
            item = asdict(match)
            item["title"] = analysis.TITLES.get(match.key, item["title"])
            item["summary"] = analysis.SUMMARIES.get(match.key, item["summary"])
            item["runnable"] = match.feasible and match.key in analysis.SUPPORTED
            item["fields"] = {key: value for key, value in match.params.items() if key in catalogue.PARAM_ROLES}
            result.append(item)
        return result

    def client(self):
        return APIClient.from_config(self.credentials_path)

    def datasets(self):
        return approved_datasets(self.client())

    def dataset_details(self, dataset_id):
        return dataset_details(self.client(), dataset_id)

    def initialise(self, project_id, dataset_id, dummy=False):
        root = self.project(project_id)["path"]
        client = self.client()
        require_approved(client, dataset_id)
        def work(job):
            result = initialise_project(root, dataset_id, client, dummy, job.emit)
            with self.lock:
                self.profiles.pop(project_id, None)
            with self.registry() as entries:
                for entry in entries:
                    if entry["id"] == project_id:
                        entry["dataset_id"] = dataset_id
            self.audit(project_id, "project.initialised", {"dataset_id": dataset_id})
            return result
        return self.jobs.submit(project_id, "initialise", project_id + ":initialise", work)

    def plan(self, project_id, thread_id, key, fields=None, *, request_id=None):
        plan = analysis.make_plan(self.project(project_id)["path"], key, fields, profile=self.profile(project_id))
        request_key = json.dumps([key, fields], sort_keys=True)
        if request_id and thread_id:
            for previous in self.store.objects(project_id, "plan", thread_id):
                if previous.get("request_id") == request_id and previous.get("request_key") == request_key:
                    return previous
        if thread_id:
            self.store.thread(project_id, thread_id)
        else:
            thread_id = self.store.create_thread(project_id, plan["title"])["id"]
        plan = self.store.put(project_id, "plan", dict(plan, request_id=request_id, request_key=request_key), thread_id)
        self.audit(project_id, "plan.created", {"plan_id": plan["id"], "analysis": key})
        return plan

    def run(self, project_id, plan_id):
        project = self.project(project_id)
        plan = self.store.get(project_id, "plan", plan_id)
        def work(job):
            job.emit("validate", "Revalidating the plan and pinned input files…")
            result = artifact_view(analysis.run_plan(project["path"], plan, profile=self.profile(project_id)))
            job.emit("save", "Saving the reviewed local preview and reproducible code…")
            artifact = self.store.put(project_id, "artifact", result, plan["thread_id"])
            self.store.message(project_id, plan["thread_id"], "assistant",
                               "Your preview is saved. Choose View saved preview to open its chart and table in Results.")
            self.audit(project_id, "artifact.created", {"artifact_id": artifact["id"], "code_digest": artifact["code_digest"]})
            return artifact
        return self.jobs.submit(project_id, "preview", project_id + ":preview:" + plan_id, work)

    def audit(self, project_id, kind, payload):
        if not self.record:
            return
        # Keep the existing .epsilon/chat transcripts untouched. This log has
        # references and decisions, never credentials, source data or outputs.
        directory = self.state_dir / "audit"
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / (project_id + ".jsonl")
        if not all(c.isalnum() or c in "-_" for c in project_id):
            raise PublicError("Invalid project identifier.")
        with self.lock:
            fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a") as stream:
                stream.write(json.dumps({"time": now(), "kind": kind, **payload}) + "\n")

    def ai_config(self, refresh=False):
        """Resolve credentials once per configuration, never once per cell.

        External CLI configuration/environment changes invalidate the cache.
        Keychain reads happen at resolution, not in saves or error handlers.
        """
        with self.ai_lock:
            custom = self.store.setting("ai")
            chosen = self.store.setting("ai_model")
            path = Path(llm.config.config_path())
            stamp = (path.stat().st_mtime_ns, path.stat().st_size) if path.exists() else None
            key = (json.dumps([custom, chosen], sort_keys=True), stamp, self.memory_key,
                   tuple(os.environ.get(name) for name in llm.config.ENV_KEYS))
            if not refresh and self._ai_cache and self._ai_cache[0] == key:
                return replace(self._ai_cache[1])
            config = self._resolve_ai_config(custom)
            # A model chosen in the chat or Settings rides on the saved
            # connection, so the credential stored for it stays valid. It is
            # ignored once the connection itself points somewhere else.
            if chosen and chosen.get("provider") == config.provider and chosen.get("base_url") == config.base_url:
                config.model = chosen["model"]
            self._ai_cache = (key, replace(config))
            return config

    def _resolve_ai_config(self, custom):
        if custom is None:
            return llm.load()
        config = llm.AIConfig(**custom)
        config.api_key = self.memory_key
        config.key_source = "workspace session" if self.memory_key else None
        if not config.api_key:
            ring = llm.config.keyring_backend()
            if ring:
                try:
                    config.api_key = ring.get_password("epsilon-workbench", self._ai_account(custom))
                    config.key_source = "OS keyring" if config.api_key else None
                except Exception:
                    pass
        return config

    @staticmethod
    def _ai_account(config):
        return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()

    def ai_status(self):
        with self.ai_lock:
            config = self.ai_config()
            return {"configured": config.configured, "provider": config.provider, "model": config.model,
                    "base_url": config.base_url or "", "key_source": config.key_source,
                    "rates": pricing.rates(config.provider, config.model, self.store.setting("ai_prices", {}), config.base_url),
                    "source": "workspace" if self.store.setting("ai") else "epsilon ai login",
                    "sharing": "Your questions, saved research goal, schema field names/types, column names you confirmed, generated template code, AI code suggestions and unchanged AI-written cells. Use with AI can share one reviewed cell for one request. Dataset rows, observed values, notebook outputs and other manual edits are not sent automatically."}

    def configure_ai(self, provider, model, base_url, api_key, persist):
        with self.ai_lock:
            if provider not in llm.config.PROVIDERS or not model.strip():
                raise PublicError("Choose a supported provider and enter its model name.")
            problem = llm.config.check_base_url(base_url)
            if problem:
                raise PublicError(problem)
            settings = {"provider": provider, "model": model.strip(), "base_url": base_url or None, "tier": llm.TIER_A}
            old = self.store.setting("ai")
            current = self.ai_config()
            if (not api_key and current.configured and current.model != settings["model"] and
                    (current.provider, current.base_url) == (provider, settings["base_url"])):
                # Only the model changed: keep the connection and its key.
                return dict(self.set_model(settings["model"]), saved_in=current.key_source, credential_cleanup=True)
            if not api_key and old != settings and provider != "openai-compatible":
                raise PublicError("Enter an API key for the new model configuration.")
            if provider == "openai-compatible" and not base_url:
                raise PublicError("Enter the institution or local model endpoint.")
            if old != settings:
                self.memory_key = None
            source = "workspace session"
            if api_key:
                self.memory_key = api_key
                if persist:
                    ring = llm.config.keyring_backend()
                    if ring:
                        try:
                            ring.set_password("epsilon-workbench", self._ai_account(settings), api_key)
                            source = "OS keyring"
                        except Exception:
                            pass
            cleanup = self._remove_workspace_key(old) if old and old != settings else True
            if api_key and not persist and old == settings:
                cleanup = self._remove_workspace_key(old)
            self.store.set_setting("ai", settings)
            self.store.set_setting("ai_model", None)
            self._ai_cache = self._models_cache = None
            return dict(self.ai_status(), saved_in=source, credential_cleanup=cleanup)

    def set_model(self, model):
        """Switch model on the active connection, from the chat or Settings."""
        model = (model or "").strip()
        if not model or len(model) > 150 or any(ord(c) < 32 for c in model):
            raise PublicError("Enter a model name.")
        with self.ai_lock:
            config = self.ai_config()
            if not config.configured:
                raise PublicError("Connect AI in Settings before choosing a model.")
            self.store.set_setting("ai_model", {"provider": config.provider, "base_url": config.base_url, "model": model})
            self._ai_cache = None
            return self.ai_status()

    SUGGESTED_MODELS = {
        "anthropic": ["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5", "claude-fable-5-1"],
        "openai": ["gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini"],
    }

    def ai_models(self, refresh=False):
        """Models the saved credential can call, asked of the provider itself.

        The request carries the API key and nothing else. When the provider
        cannot list models, a short suggested list stands in and says so.
        """
        with self.ai_lock:
            config = self.ai_config()
            if not config.configured:
                return {"models": [], "current": config.model, "source": "none"}
            key = (config.provider, config.base_url, hashlib.sha256((config.api_key or "").encode()).hexdigest())
            cached = self._models_cache
            if not refresh and cached and cached[0] == key and time.monotonic() - cached[1] < 600:
                models, source = cached[2], cached[3]
            else:
                try:
                    provider = llm.build(config)
                    provider.timeout = 10
                    models, source = provider.list_models(), "provider"
                except (LLMError, NotImplementedError, ValueError):
                    models, source = [], "suggested"
                if not models:
                    models = [{"id": m, "label": m} for m in self.SUGGESTED_MODELS.get(config.provider, [])]
                    source = "suggested"
                self._models_cache = (key, time.monotonic(), models, source)
            custom = self.store.setting("ai_prices", {})
            if config.model and all(m["id"] != config.model for m in models):
                models = [{"id": config.model, "label": config.model}] + models
            return {"current": config.model, "source": source,
                    "models": [dict(m, rates=pricing.rates(config.provider, m["id"], custom, config.base_url)) for m in models]}

    def set_price(self, model, input_rate, output_rate):
        """The researcher's own US$ per million tokens for one model, or None to clear."""
        model = (model or "").strip()
        if not model or len(model) > 150:
            raise PublicError("Choose the model these rates apply to.")
        with self.ai_lock:
            prices = dict(self.store.setting("ai_prices", {}))
            if input_rate is None and output_rate is None:
                prices.pop(model, None)
            elif input_rate is None or output_rate is None:
                raise PublicError("Enter both an input and an output rate, or clear both.")
            else:
                if len(prices) >= 50 and model not in prices:
                    raise PublicError("Remove a saved rate before adding another.")
                prices[model] = {"input": input_rate, "output": output_rate}
            self.store.set_setting("ai_prices", prices)
            return self.ai_status()

    def record_usage(self, project_id, kind, meter, connection, thread_id=None, request_id=None):
        """Save what a request spent. Tokens are counted even when it failed."""
        if not meter.calls:
            return
        provider, model = connection.get("provider") or "unknown", connection.get("model") or "unknown"
        applied = pricing.rates(provider, model, self.store.setting("ai_prices", {}), connection.get("base_url"))
        # A backend that reports no usage has an unknown cost, not a zero one.
        spent = pricing.cost(meter.usage, applied) if meter.usage.total_tokens else None
        self.store.record_usage(project_id, thread_id, request_id, kind, provider, model, meter.usage, meter.calls, spent)

    def _remove_workspace_key(self, settings):
        if not settings:
            return True
        ring = llm.config.keyring_backend()
        if not ring:
            return True
        try:
            if ring.get_password("epsilon-workbench", self._ai_account(settings)) is None:
                return True
            ring.delete_password("epsilon-workbench", self._ai_account(settings))
            return True
        except Exception:
            return False

    def use_cli_ai(self):
        with self.ai_lock:
            cleanup = self._remove_workspace_key(self.store.setting("ai"))
            self.memory_key = None
            self.store.set_setting("ai", None)
            self.store.set_setting("ai_model", None)
            self._ai_cache = self._models_cache = None
            return dict(self.ai_status(), credential_cleanup=cleanup)

    def provider(self):
        config = self.ai_config()
        if not config.configured:
            raise PublicError("Connect a model in Settings, or use the deterministic analysis cards.")
        provider = llm.build(config)
        provider.timeout = 60
        return provider

    def test_ai_connection(self):
        """A researcher-triggered check with no project or conversation context."""
        from sdk.llm.base import Turn
        from sdk.workbench.assistant import TOOLS

        if not self.ai_status()["configured"]:
            return {"connected": False, "message": "Save an AI connection in Settings first."}
        try:
            provider = self.provider()
            provider.timeout = 25
            provider.converse("This is a connection check. Reply only OK; do not call tools.",
                              [Turn("user", text="Connection check")], TOOLS, max_tokens=64)
        except LLMError as exc:
            return {"connected": False, "message": exc.public_message}
        # No provider text, tool calls or request bodies are returned or saved.
        return {"connected": True, "message": "Connection successful. The provider accepted a chat request with notebook tools."}

    def known_secrets(self):
        values = [self.ai_config().api_key]
        values.extend(credentials.stored_secrets(self.credentials_path))
        return values

    def import_history(self, project_id):
        self.project(project_id)
        source = self.state_dir / "chat.db"
        if not source.exists():
            return {"imported": 0}
        imported = 0
        # Open the legacy database read-only; preserve it and its transcripts.
        with self.lock:
            db = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
            db.row_factory = sqlite3.Row
            try:
                threads = db.execute('SELECT * FROM threads WHERE "userIdentifier"=?', ("project:" + project_id,)).fetchall()
                for old in threads:
                    marker = "legacy:" + project_id + ":" + old["id"]
                    if self.store.setting(marker):
                        continue
                    thread = self.store.create_thread(project_id, old["name"] or "Imported conversation")
                    rows = db.execute('SELECT * FROM steps WHERE "threadId"=? ORDER BY "createdAt",rowid', (old["id"],)).fetchall()
                    for row in rows:
                        if row["type"] in ("user_message", "assistant_message"):
                            role = "user" if row["type"] == "user_message" else "assistant"
                            text = row["output"] or row["input"] or ""
                            if text:
                                # Earlier assistants could put measured values
                                # in text. Import for display, never automatic
                                # outbound context under the new contract.
                                self.store.message(project_id, thread["id"], role, text, shareable=False)
                    self.store.set_setting(marker, thread["id"])
                    imported += 1
            except sqlite3.Error:
                raise PublicError("The legacy history database has an unsupported schema. It has not been modified.")
            finally:
                db.close()
        return {"imported": imported, "note": "Text imported. Charts that were never stored cannot be reconstructed."}
