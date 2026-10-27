# AIRAN-PoC
PoC project for MITLab at NTUST under Taiwanese IIPP.

## The Assignment

“Maybe they could conduct a small-scale trial by developing an AI-RAN proof of concept controlled by Agentic AI, using NVIDIA Spark as an all-in-one platform to demonstrate both AI-for-RAN and AI-on-RAN capabilities”

## AI Agent

All relevant scripts and config files are in [agent](agent/) folder.
[config](agent/config/) contains core files for the AI agent, [cron](agent/cron/) contains files for setting up the two cron jobs described in the report.

If the agent is not running and should be, refer to [the other doc](agent_troubleshoot.md).

To get to the dashboard, it should be possible to just open the browser (on the Spark) and go to `127.0.0.1:18789` or `127.0.0.1:18790`. The page is likely to ask for a token, which can be obtained by typing
```bash
nemoclaw ayran-agent gateway-token
```
in Spark terminal (host, outside of the sandbox).

To set up a new agent, prepare a model host and do `nemoclaw onboard`.
The following sections should contain everything needed to go through the interactive onboarding towards our result.

Once the sandbox is set up, use the core files in [agent/config](/agent/config/) to remove all the context bloat, emoji answers and so on.

Check `/sandbox/.openclaw/openclaw.json` and see if `skipBootstrap` is set to `false` and if `contextWindow` and `maxTokens` are set to your model host parameters.

### OpenClaw

There are other options, but we only worked with OpenClaw for this project. All that is needed in the onboarding is pretty much just choosing OpenClaw in the first step and following the guide.

### Model Host

In provider menu, there are several options, two of which we tested. This may be due to some improper setup of thinking, but SGLang performed better in our testing.

Setting up Ollama is easy, for SGLang, do `4) Other OpenAI-compatible endpoint` and go from there. Further details in their respective sections below.

#### Ollama

Runs, but seems slow. Installed directly on the Spark. Not used after speed issues.

Installed via `curl -fsSL https://ollama.com/install.sh | sh`. Then find a model on their website and download using provided link, i.e. `ollama run qwen3.8`.

#### SGLang

Installed via docker using `docker pull lmsysorg/sglang:latest-cu130`. Used launch command is
```bash
docker run -d --gpus all \
  --shm-size 32g \
  -p 30000:30000 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  --name sglang-qwen38 \
  lmsysorg/sglang:latest-cu130 \
  python3 -m sglang.launch_server \
    --model-path Qwen/Qwen3.8-27B-FP8 \
    --host 0.0.0.0 \
    --port 30000 \
    --context-length 262144 \
    --mem-fraction-static 0.8 \
    --default-chat-template-kwargs '{"enable_thinking": false}' \
    --reasoning-parser qwen3 \
    --tool-call-parser qwen3_coder
```

It takes some time to launch[^2], so check `docker logs -f sglang-qwen38` to see how the startup process is going. On done, the log will say
```
[YYYY-MM-DD HH:mm:ss] The server is fired up and ready to roll!
```

[^2]: like a lot. When downloading a new model the size of Qwen3.8-27B, this can take up to an hour.

Once running, you should see the IP (should be localhost) and port in the log. Set up an api key using `export SGLANG_API_KEY="sglang-local"` or any other key of choice.

Check your model(s) using `curl http://127.0.0.1:30000/v1/models`. This will be needed during onboarding.

Once running `nemoclaw onboard`, pick "4) Other OpenAI-compatible endpoint" (or similar) and give the IP:port/v1 (`http://host.openshell.internal:30000/v1`[^3]), the set api key (`slang-local`) and the model name checked earlier (`Qwen/Qwen3.8-27B`).

[^3]: `127.0.0.1` points to the sandbox, so the host's local is different fromthe sandbox

### Setting up the Cron Job

There are two ways, either use dashboard GUI or use `openclaw cron` in CLI (inside the sandbox).

#### In GUI

> [!CAUTION]
> This option requires a fixed typed out prompt, which a waste of resources given the file manipulation can be solved with a [simple bash script](/agent/cron/infer_cron.sh).
> It is highly recommended to skip this section and go straight to [CLI job creation](#in-cli).

This is quite simple. Open the dashboard and go to "Cron Jobs":

![Openclaw dashboard sidebar showing Cron jobs in red](/img/openclaw_dashboard_sidebar.png)

You should see a bar saying Con jobs are enabled at the top. On the right side of this bar, there is an option to create a new job:

![The view of Cron Jobs tab once opened](/img/openclaw_cron_main.png)

The GUI walk you through the job creation process. First set up the name and the prompt. If the job neds to look for data in files that may or may not show up, the prompt needs to contain information as to how to find them and what to do with them:

![First step in creating a cron job in GUI](/img/openclaw_job_creation_1.png)

Set job run schedule:

![Second step in creating a cron job in GUI](/img/openclaw_job_creation_2.png)

And finally set up which model to use and where to send the response. We have no channel (Telegram, Discord,...) so we run in independent session:

![Final step in creating a cron job in GUI](/img/openclaw_job_creation_3.png)

Once created, the job will be listed in the Cron Jobs tab with any other jobs created in that sandbox.
The job can be modified under Edit next to its name in the list.

#### In CLI

This option is superior in terms of ability to customize and it is the one we went with. On the Spark, connect to the agent sandbox and work from within it.

To create an automated job, use
```bash
openclaw cron add \
    --name "job name" \
    --every 1m \
    --command "path/to/script/in/sandbox.sh" \
    --timeout-seconds 600 \
    --no-deliver
```
for no out (except inside the OpenClaw chat), or
```bash
openclaw cron add \
    --name "RANalyze30s" \
    --every 30s \
    --command /sandbox/cron_scripts/infer_cron.sh \
    --timeout-seconds 480 \
    --announce --channel discord --to "channel:1559429768112250920"
```
for output into discord channel

modifying parameters to the job's specific needs.
Jobs can be modified after creation using
```bash
openclaw cron edit <job-id> --<flag-to-edit> <value-if-applicable>
```
or disabled using
```bash
openclaw cron disable <job-id>
```
To restart the job schedule, replace `disable` with `enable`. To remove the job altogether, run
```bash
openclaw cron rm <job-id>
```

It is a good idea to check the functionality using
```bash
openclaw cron run <job-id> --wait
```
where the `--wait` makes the terminal give back control only after the job finishes.

To see what jobs are currently queued, use
```bash
openclaw cron list
```

### Channels Integration

OpenClaw allows several services to be used for communication with the Agent via traditional chat.
We decided to go with Discord.

The setup process requires an existing Discord server in which you have admin privileges.

#### Setting Up Bot on Discord

Go to [Discord developer portal](https://discord.com/developers/home) and log in.
Click `+ Create` in top right corner and choose "Build a bot for your server or community".
Give the bot a name, agree to terms of service and click "Create".

Once created, youshould land in bot management page.
Navigate to "Bot" panel and make sure "Requires OAuth2 Code Grant" is off and "Message Content Intent" is on.

Move to "OAuth2" panel and pick "Bot" under "Scopes" in "OAuth2 URL Generator".
You may set them up as follows.
![discrod bot perms example](img/discord_bot_permissions.png)
Copy the generated URL and paste it into browser to invite the bot to your server.

#### Adding the Bot to OpenClaw

To connect the bot with OpenClaw Agent, you need bot token and server ID.
Bot token can be obtained from developer portal under "bot" panel.
For server ID, enable developer mode in Discord (User Settings > Developer > Developer Mode), right click server icon and "Copy Server ID".

If you need to restrict access to the bot to one user, get user ID as well.
For our application, we can limit this by containing the bot to a set of private channels in the discrod server.

##### During Onboarding

Preferred option, not tested.

##### To an Existing Agent

On host side on the Spark, set the token and IDs. 
```bash
export DISCORD_BOT_TOKEN="<token>"
export DISCORD_SERVER_ID="<server-id>"
export DISCORD_USER_ID="<your-user-id>"   # optional
```

Add discord as a channel and rebuild.

> [!CAUTION]
> This rebuilds the agent sandbox and data inside may be lost.
> Make sure to backup any data and/or scripts in the sandbox to upload them after the rebuild.
> 
> In our testing this also caused the pending scope approval deadlock, so be prepared to deal with it if it occurs.

```bash
nemoclaw ayran-sgl channels add discord
nemoclaw ayran-sgl rebuild                  # if not done while adding channel
```

#### Once Set Up

Once set up, and running, the bot should drop messages to the channel.

![Discord log channel](img/discord_log.png)

If set up properly, the bot can ping users and roles to ask for intervention.

![Discord notification](img/discord_notif.png)

The bot is an interface to the agent, so users can directly interact with the agent through the channel.

![User nteraction](img/discord_interaction.png)

## OpenAirInterface

TBA

## Integration

[spark_host](spark_host/) folder contains scripts to deploy once OAI and NemoClaw is set up.

### [base_station.py](spark_host/base_station.py)

Runs the base station and picks up the diagnostic data. Every _x_ minutes, it dumps the whole thing into a .txt file.
Run as `python base_station.py sudo cgexec -g cpuset:oai_gnb path/to/oai/openairinterface5g/cmake_targets/ran_build2/build/nr-softmodem -O path/to/gnb/CONF.conf --rfsim --telnetsrv`. Specific path may vary on your OAI build specifics.

### [sbx_iface.py](spark_host/sbx_iface.py)

Takes base station dumpfiles and uploads them into the NemoClaw sandbox. Checks for files every `-w` seconds and deletes old ones if specified using `-c`.
Theoretically should call an API, but actually steers via telnet.

### [agent/cron/infer_cron.sh](agent/cron/infer_cron.sh)

Checks /tmp (inside the agent sandbox) for new files matching diagdata_\<date\>.csv and and sends the path to the model if new one is found. Dumps the answer to /sandbox/agent_responses/response_\<date\>.json.
