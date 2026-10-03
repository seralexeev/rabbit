import asyncio
import json
import os
import shlex

from lib.node import RabbitNode
from lib.power_supervisor import JETSON_SUBJECT
from nats.aio.msg import Msg

COMMANDS = {"poweroff": "systemctl poweroff", "reboot": "systemctl reboot"}


class Node(RabbitNode):
    REPLY_GRACE_S = 0.5

    def __init__(self):
        super().__init__("jetson-power")
        self.dry_run = os.environ.get("POWER_DRY_RUN") == "1"

    async def init(self):
        await self.subscribe(JETSON_SUBJECT, self.on_request)

    async def on_request(self, msg: Msg):
        request = json.loads(msg.data or b"{}")
        action, source = str(request.get("action", "")), str(request.get("source") or "unknown")
        command = COMMANDS.get(action)
        self.event("power.jetson_requested", f"{action} from {source}", severity="warning" if command else "error", action=action, source=source, accepted=command is not None, dry_run=self.dry_run)
        if msg.reply:
            await self.publish_json(msg.reply, {"ok": command is not None, "action": action})
        if command is None:
            return
        await self.publish_logs()
        await asyncio.sleep(self.REPLY_GRACE_S)
        if not self.dry_run:
            await asyncio.create_subprocess_exec(*shlex.split(command))


if __name__ == "__main__":
    Node().run_node()
