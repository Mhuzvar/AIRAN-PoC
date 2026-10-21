# Troubleshooting the Agent

This doc contains hints on how to solve some of the issues we encountered.

## Dashboard not Running

Connect to the sandbox and run
```bash
openclaw gateway run
openclaw dashboard
```
This _should_ show you the URL and gateway token to open the dashboard in browser. If it doesn't give you the token, use
```bash
nemoclaw ayran-agent gateway-token
```
outside of the sandbox.

## OpenClaw not Running

Sometimes the agent refuses to start. Try
```bash
nemoclaw ayran-agent rebuild --force
```

## Making a Snapshot and Reloading it

If the container was restarted, the system falls into a deadlock and cannot do anything. This is *likely* due to non-persistent storage of the sandbox. To make a snapshot when something new was added and everything works fine, run the following from outside the sandbox:


```bash
nemoclaw ayran-agent shields down
nemoclaw ayran-agent snapshot create --name pre-rebuild-$(date +%Y%m%d)
nemoclaw ayran-agent download /sandbox/.openclaw/identity ./openclaw-identity-backup
nemoclaw ayran-agent download /sandbox/.openclaw/devices ./openclaw-devices-backup
nemoclaw ayran-agent shields up
```

If the deadlock occurs, restore using the following:

```bash
nemoclaw ayran-agent snapshot restore <the-snapshot-made-earlier>
nemoclaw ayran-agent upload ./openclaw-identity-backup/device.json /sandbox/.openclaw/identity/device.json
nemoclaw ayran-agent upload ./openclaw-identity-backup/device-auth.json /sandbox/.openclaw/identity/device-auth.json
nemoclaw ayran-agent upload ./openclaw-devices-backup/paired.json /sandbox/.openclaw/devices/paired.json
nemoclaw ayran-agent exec -- sh -c 'echo "{}" > /sandbox/.openclaw/devices/pending.json'
nemoclaw ayran-agent exec -- openclaw gateway restart
nemoclaw ayran-agent exec -- openclaw devices list --json
```

> [!WARNING] 
> It turns out this doesn't reliably fix the issue.
> The only way to fix it is manually approving the pending device.

### Manual Fix to the Deadlock

The only way to actually and reliably resolve the deadlock is to manually approve the pending device.

Get list of devices to see which is hung in the deadlock
```bash
nemoclaw ayran-sgl exec -- openclaw devices list --json
```

Grant it admin manually
```bash
nemoclaw ayran-sgl exec -- node -e '
const fs = require("fs");
const p = "/sandbox/.openclaw/devices/paired.json";
const data = JSON.parse(fs.readFileSync(p, "utf8"));
const id = "<deviceId-from-above>";
const scopes = ["operator.pairing", "operator.read", "operator.write", "operator.admin"];
data[id] = data[id] || {};
data[id].scopes = scopes;
data[id].approvedScopes = scopes;
data[id].tokens = data[id].tokens || { operator: {} };
data[id].tokens.operator.scopes = scopes;
fs.writeFileSync(p, JSON.stringify(data, null, 2));
console.log("updated");
'
```

Check if the issue got resolved, restart the gateway, check again.
```bash
nemoclaw ayran-sgl exec -- sh -c 'echo "{}" > /sandbox/.openclaw/devices/pending.json'
nemoclaw ayran-sgl exec -- openclaw gateway restart
nemoclaw ayran-sgl exec -- openclaw devices list --json
```

### Worst Case

If something went terribly wrong, the entire thing may need to be remade from scratch. First, make a backup of anything necessary. To delete the agent, use
```bash
nemoclaw ayran-agent destroy
```
which completely removes the agent along with the sandbox and anything inside. It is a good idea to reboot the system now, but it shouldn't be necessary. Once rebooted (or not), make a new agent using
```bash
nemoclaw onboard
```
which guides you through agent creation.

# Known Issues

The version numbers are MMDD of when the pipeline was last modified. This is just to track whether the issue may have been solved already.

## 0825 Version (neither occured the in last version)

For some reason, the agent sometimes fails to open the files on first try and then proceeds to spend some time running in circles of trying different ways to access the data. How long and how many steps this takes seems random.

![An example of the agent not knowing how to open a file](/img/tool_use_fails.png)

Sometimes the agent also just refuses to acknowledge the message is a filepath and just doesn't analyze the data. Might be caused by context getting full but again, seemingly random.

![Agent refusing to work](/img/ai_stumble.png)

Quite often the agent just flat out refuses to acknowledge the file exists. In testing this happened with context window filled to between 40% and 80%.

![Agent not seeing the file](/img/ai_not_seeing_files.png)

When the base station is idle and nothing happens for a few frames the agent skips the response sometimes. Not harmful on its own but good to know.

![Agent not producing output](/img/ai_no_output.png)

