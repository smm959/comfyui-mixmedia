import { app } from "../../scripts/app.js";

/*
 * Кнопка «СТАРТ» на каждом этапе фотостудии.
 * Нажатие включает этот этап (run = ЭТАП ВКЛЮЧЁН), выключает остальные и сразу ставит очередь,
 * поэтому один клик = одна генерация этого этапа, без ручного щёлканья тумблерами.
 */

const STAGES = {
  MixmediaCharacter: "лист персонажа",
  MixmediaShot: "кадр",
  MixmediaRetake: "докрутка",
};

function toast(summary, severity = "info", detail = "") {
  try {
    app.extensionManager?.toast?.add({ severity, summary, detail, life: 5000 });
  } catch (err) {
    console.info("[mixmedia]", summary, detail);
  }
}

function runWidget(node) {
  return node.widgets?.find((w) => w?.name === "run");
}

function setRun(node, value) {
  const w = runWidget(node);
  if (!w) return false;
  w.value = value;
  return true;
}

async function queuePrompt() {
  if (typeof app.queuePrompt === "function") return app.queuePrompt(0, 1);
  const command = app.extensionManager?.command;
  if (command?.execute) return command.execute("Comfy.QueuePrompt");
  const button = document.querySelector("#queue-button, .comfyui-button.queue");
  if (button) return button.click();
  throw new Error("не нашёл кнопку запуска");
}

async function startStage(node) {
  const graph = app.graph;
  if (!graph) return;

  const stages = (graph._nodes || []).filter((n) => STAGES[n.type]);
  if (!stages.includes(node)) return;

  const touched = stages.map((n) => setRun(n, n === node)).some(Boolean);
  if (!touched) {
    toast("в этой ноде нет тумблера run", "error");
    return;
  }

  graph.setDirtyCanvas(true, true);
  const off = stages.filter((n) => n !== node).map((n) => STAGES[n.type]);
  toast(
    `Старт: этап ${STAGES[node.type]}`,
    "success",
    off.length ? `выключил: ${off.join(", ")}` : "",
  );

  try {
    await queuePrompt();
  } catch (err) {
    console.error("[mixmedia] не удалось поставить в очередь", err);
    toast("Не удалось запустить", "error", String(err?.message || err));
  }
}

function addStartButton(node) {
  const label = STAGES[node.type];
  if (!label || node.__mixmediaStart) return;

  const widget = node.addWidget("button", `▶ СТАРТ — ${label}`, null,
    () => { void startStage(node); },
    { serialize: false, surfaces: { canvas: "shown", vueNode: "shown", panel: "never" } });
  if (!widget) return;

  // кнопка не должна попадать в widgets_values: иначе поедут значения виджетов в JSON
  widget.serialize = false;
  widget.serializeValue = () => undefined;
  widget.options = { ...(widget.options || {}), serialize: false };
  node.__mixmediaStart = widget;

  try {
    const size = node.computeSize?.();
    if (size) node.setSize?.([Math.max(node.size[0], size[0]), Math.max(node.size[1], size[1])]);
  } catch (err) {
    console.warn("[mixmedia] не смог подогнать размер ноды", err);
  }
}

app.registerExtension({
  name: "mixmedia.stage-buttons",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!STAGES[nodeData.name]) return;
    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = onCreated?.apply(this, arguments);
      addStartButton(this);
      return result;
    };
  },
});
