"""Container-only Jupyter bridge. Never launched as a host-code fallback."""
import json
import sys
import time
from queue import Empty

MAX_TEXT = 120000
MAX_TOTAL = 850000
MAX_BLOCKS = 32
MIMES = ("text/plain", "text/html", "text/markdown", "application/json", "image/png", "application/vnd.epsilon.preview+json")


class Outputs:
    """Collect ordered, bounded Jupyter MIME bundles; never execute a renderer."""
    def __init__(self):
        self.items = []
        self.waiting_clear = False
        self.truncated = False
        self.error = False
        self.execution_count = None

    def feed(self, kind, content):
        if kind == "execute_input":
            self.execution_count = content.get("execution_count")
            return
        if kind == "clear_output":
            self.waiting_clear = bool(content.get("wait"))
            if not self.waiting_clear:
                self.items.clear()
            return
        if kind not in ("stream", "error", "execute_result", "display_data", "update_display_data"):
            return
        if self.waiting_clear:
            self.items.clear()
            self.waiting_clear = False
        item = {"output_type": kind}
        if kind == "stream":
            value = str(content.get("text", ""))
            self.truncated |= len(value) > MAX_TEXT
            item.update(name="stderr" if content.get("name") == "stderr" else "stdout", text=value[:MAX_TEXT])
            if self.items and self.items[-1].get("output_type") == "stream" and self.items[-1]["name"] == item["name"]:
                previous = self.items.pop()
                value = previous["text"] + item["text"]
                self.truncated |= len(value) > MAX_TEXT
                item["text"] = value[:MAX_TEXT]
        elif kind == "error":
            self.error = True
            trace = content.get("traceback")
            value = "\n".join(str(line) for line in trace[:20]) if isinstance(trace, list) else str(content.get("ename", "Error")) + ": " + str(content.get("evalue", ""))
            item["text"] = value[:MAX_TEXT]
            self.truncated |= len(value) > MAX_TEXT
        else:
            data = content.get("data")
            item["data"] = {}
            if isinstance(data, dict):
                for mime in MIMES:
                    if mime not in data:
                        continue
                    value = data[mime]
                    try:
                        size = len(json.dumps(value, allow_nan=False))
                    except (TypeError, ValueError, RecursionError):
                        continue
                    if size <= (500000 if mime == "image/png" else MAX_TEXT):
                        item["data"][mime] = value
                    else:
                        self.truncated = True
            if not item["data"]:
                item["data"] = {"text/plain": "This output format is unavailable. Use a static table or PNG figure."}
            transient = content.get("transient")
            display_id = transient.get("display_id") if isinstance(transient, dict) else None
            if isinstance(display_id, str) and len(display_id) <= 100:
                item["display_id"] = display_id
        if len(self.items) >= MAX_BLOCKS or len(json.dumps(self.items)) + len(json.dumps(item)) > MAX_TOTAL:
            self.truncated = True
        else:
            self.items.append(item)


def main():
    from jupyter_client import KernelManager
    manager = KernelManager(kernel_name="python3")
    manager.start_kernel(cwd="/workspace", stdout=sys.stderr, stderr=sys.stderr)
    client = manager.client()
    client.start_channels()
    try:
        client.wait_for_ready(timeout=30)
        setup = client.execute("%matplotlib inline", silent=True, store_history=False)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                message = client.get_iopub_msg(timeout=1)
            except Empty:
                continue
            if message.get("parent_header", {}).get("msg_id") == setup and message["header"]["msg_type"] == "status" and message["content"].get("execution_state") == "idle":
                break
        else:
            raise RuntimeError("Inline plotting could not be initialised.")
        print(json.dumps({"ready": True, "protocol": 2}), flush=True)
        for line in sys.stdin:
            request = json.loads(line)
            message_id = client.execute(request["code"], store_history=True, allow_stdin=False, stop_on_error=True)
            output = Outputs()
            deadline = time.monotonic() + min(request.get("timeout", 30), 60)
            while time.monotonic() < deadline:
                try:
                    message = client.get_iopub_msg(timeout=1)
                except Empty:
                    continue
                if message.get("parent_header", {}).get("msg_id") != message_id:
                    continue
                kind, content = message["header"]["msg_type"], message["content"]
                if kind == "status" and content.get("execution_state") == "idle":
                    break
                output.feed(kind, content)
            else:
                manager.interrupt_kernel()
                print(json.dumps({"id": request["id"], "error": True, "text": "Execution timed out. Restart the kernel before continuing.", "restart_required": True}), flush=True)
                break
            print(json.dumps({"id": request["id"], "outputs": output.items,
                              "execution_count": output.execution_count,
                              "error": output.error, "truncated": output.truncated}), flush=True)
    finally:
        client.stop_channels()
        manager.shutdown_kernel(now=True)


if __name__ == "__main__":
    main()
