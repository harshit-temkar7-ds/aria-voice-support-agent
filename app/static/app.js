
const $ = (id) => document.getElementById(id);
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

let active = false;
let busy = false;
let rec = null;
let history = [];
let toolEvents = [];
let voice = null;

// ---------- UI helpers ----------

function setState(state) {
  const el = $("state");
  el.textContent = state;
  el.className = "state " + state.toLowerCase();
}

function notice(message) {
  $("notice").textContent = message || "";
}

function addMsg(role, text) {
  history.push({ role, content: text });

  const div = document.createElement("div");
  div.className = "msg " + role;

  const label = document.createElement("b");
  label.textContent = role === "user" ? "Customer" : "Aria";

  div.appendChild(label);
  div.appendChild(document.createElement("br"));
  div.appendChild(document.createTextNode(text));

  $("transcript").appendChild(div);
  $("transcript").scrollTop = $("transcript").scrollHeight;
}

// ---------- Order-number recognition ----------

function normalizeOrderReferences(text) {
  let result = text;

  // Convert spoken versions of the three demo order IDs.
  const spokenOrders = [
    [/\b(?:order\s+(?:number\s+)?|ord\s*)?one\s+(?:zero|oh|o)\s+one\b/gi, "ORD-101"],
    [/\b(?:order\s+(?:number\s+)?|ord\s*)?one\s+(?:zero|oh|o)\s+two\b/gi, "ORD-102"],
    [/\b(?:order\s+(?:number\s+)?|ord\s*)?one\s+(?:zero|oh|o)\s+three\b/gi, "ORD-103"]
  ];

  for (const [pattern, id] of spokenOrders) {
    result = result.replace(pattern, id);
  }

  // Convert "one hundred and one" and similar spoken forms.
  const spokenHundreds = [
    [/\b(?:order\s+(?:number\s+)?|ord\s*)?one hundred (?:and )?one\b/gi, "ORD-101"],
    [/\b(?:order\s+(?:number\s+)?|ord\s*)?one hundred (?:and )?two\b/gi, "ORD-102"],
    [/\b(?:order\s+(?:number\s+)?|ord\s*)?one hundred (?:and )?three\b/gi, "ORD-103"]
  ];

  for (const [pattern, id] of spokenHundreds) {
    result = result.replace(pattern, id);
  }

  // Convert "order 101", "order number 101", "order no. 101".
  result = result.replace(
    /\border\s+(?:(?:number|no\.?)\s*)?#?\s*(\d{3})\b/gi,
    "ORD-$1"
  );

  // Convert "ord 101", "ord101", "ord-101".
  result = result.replace(
    /\bord[\s-]*#?\s*(\d{3})\b/gi,
    "ORD-$1"
  );

  // Convert "101" only when it follows order-related wording.
  return result;
}

// ---------- Feminine voice selection ----------

function pickVoice() {
  if (!("speechSynthesis" in window)) return;

  const voices = window.speechSynthesis.getVoices();

  if (!voices.length) return;

  const englishVoices = voices.filter(v =>
    v.lang && v.lang.toLowerCase().startsWith("en")
  );

  // Prefer voices commonly presented as feminine.
  const feminineVoice = englishVoices.find(v =>
    /female|zira|samantha|sonia|jenny|aria|libby|ava/i.test(v.name)
  );

  // Prefer Indian English when a suitable voice is available.
  voice =
    englishVoices.find(v =>
      v.lang.toLowerCase() === "en-in" &&
      /female|zira|samantha|sonia|jenny|aria|libby|ava/i.test(v.name)
    ) ||
    feminineVoice ||
    englishVoices.find(v =>
      v.lang.toLowerCase() === "en-in"
    ) ||
    englishVoices[0] ||
    null;
}

if ("speechSynthesis" in window) {
  pickVoice();
  window.speechSynthesis.onvoiceschanged = pickVoice;
}

function speak(text) {
  return new Promise(resolve => {
    if (!("speechSynthesis" in window)) {
      resolve();
      return;
    }

    window.speechSynthesis.cancel();

    // Voice lists can load after the page opens.
    if (!voice) pickVoice();

    const utterance = new SpeechSynthesisUtterance(text);

    utterance.lang = voice?.lang || "en-IN";
    if (voice) utterance.voice = voice;

    // Slightly slower, softer delivery.
    utterance.rate = 0.92;
    utterance.pitch = 1.12;
    utterance.volume = 1;

    let finished = false;

    const finish = () => {
      if (finished) return;
      finished = true;
      resolve();
    };

    utterance.onend = finish;
    utterance.onerror = finish;

    setState("Speaking");

    window.speechSynthesis.speak(utterance);
  });
}

// ---------- Send message to Gemini backend ----------

async function handleUser(rawText) {
  const text = normalizeOrderReferences(rawText).trim();

  if (!text || busy) return;

  busy = true;

  try {
    if (rec) rec.stop();
  } catch {}

  const priorHistory = history.slice();

  addMsg("user", text);
  setState("Thinking");
  notice("");

  let reply;

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        history: priorHistory
      })
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Request failed");
    }

    reply = data.reply;
    toolEvents.push(...(data.tool_events || []));

    // Refresh the visible order cards after operations like cancellation.
    if ((data.tool_events || []).some(event =>
      event.name === "cancel_order" ||
      event.tool === "cancel_order"
    )) {
      loadOrders();
    }
  } catch (error) {
    console.error("Chat request failed:", error);

    reply =
      "I'm sorry, I'm having a little technical trouble right now. Please try again.";

    notice(error.message || "The AI service could not respond.");
  }

  addMsg("assistant", reply);

  if (active) {
    await speak(reply);
  }

  busy = false;

  if (active) {
    listen();
  } else {
    setState("Idle");
  }
}

// ---------- Speech recognition ----------

function listen() {
  if (!active || busy) return;

  if (!SR) {
    setState("Idle");
    notice(
      "Speech recognition is not supported here. Please use Chrome or Edge, or type your message."
    );
    return;
  }

  rec = new SR();
  rec.lang = "en-IN";
  rec.interimResults = true;
  rec.continuous = false;
  rec.maxAlternatives = 5;

  let finalTranscript = "";
  let restartTimer = null;
  let submitted = false;

  rec.onstart = () => {
    setState("Listening");
    notice("Listening… Speak naturally.");
  };

  rec.onresult = (event) => {
    let interimTranscript = "";

    for (
      let i = event.resultIndex;
      i < event.results.length;
      i++
    ) {
      // Try alternative recognition results if the first one is unclear.
      const alternatives = event.results[i];
      let transcript = alternatives[0].transcript.trim();

      if (!transcript) continue;

      transcript = normalizeOrderReferences(transcript);

      if (alternatives.isFinal) {
        finalTranscript +=
          (finalTranscript ? " " : "") + transcript;
      } else {
        interimTranscript += transcript + " ";
      }
    }

    if (interimTranscript.trim()) {
      notice(
        "Hearing: " +
        normalizeOrderReferences(
          (finalTranscript + " " + interimTranscript).trim()
        )
      );
    }
  };

  rec.onerror = (event) => {
    if (
      event.error === "not-allowed" ||
      event.error === "service-not-allowed"
    ) {
      notice(
        "Microphone permission denied. Allow microphone access, or use the text box."
      );
    } else if (event.error === "audio-capture") {
      notice("No microphone was detected. Check your microphone connection.");
    } else if (
      event.error !== "aborted" &&
      event.error !== "no-speech"
    ) {
      notice("I couldn't catch that clearly. Please speak again.");
    }
  };

  rec.onend = () => {
    if (restartTimer) clearTimeout(restartTimer);

    const transcript = normalizeOrderReferences(
      finalTranscript.trim()
    );

    if (active && transcript && !busy && !submitted) {
      submitted = true;
      handleUser(transcript);
      return;
    }

    if (active && !busy) {
      restartTimer = setTimeout(listen, 500);
    }
  };

  try {
    rec.start();
  } catch (error) {
    console.error("Speech recognition start failed:", error);
    notice("Couldn't start microphone recognition. Please try again.");
  }
}

// ---------- Call controls ----------

function endUi() {
  $("start").disabled = false;
  $("end").disabled = true;
  $("typedInput").disabled = true;
  $("typedBtn").disabled = true;
  setState("Idle");
}

$("start").onclick = async () => {
  resetConvo(false);

  active = true;
  $("start").disabled = true;
  $("end").disabled = false;
  $("typedInput").disabled = false;
  $("typedBtn").disabled = false;

  let micOk = !!SR;

  if (!SR) {
    notice(
      "Speech recognition isn't supported in this browser. Use Chrome or Edge, or type below."
    );
  } else {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: true
      });

      stream.getTracks().forEach(track => track.stop());
    } catch {
      micOk = false;
      notice(
        "Microphone permission denied. Allow microphone access, or use the text box below."
      );
    }
  }

  const greeting =
    "Namaste! Welcome to Aura Skincare. I'm Aria. How may I help you today?";

  addMsg("assistant", greeting);
  await speak(greeting);

  if (micOk && active) {
    listen();
  } else {
    setState("Idle");
  }
};

function renderSummary(data) {
  const container = $("summary");
  container.replaceChildren();
  container.className = "summary-content";

  const fields = [
    ["Customer intent", data.customer_intent || "OTHER"],
    ["Order ID", data.order_id || "Not identified"],
    ["Resolution status", data.resolution_status || "UNRESOLVED"]
  ];

  for (const [label, value] of fields) {
    const card = document.createElement("div");
    card.className = "summary-stat";
    const caption = document.createElement("span");
    caption.textContent = label;
    const content = document.createElement("strong");
    content.textContent = String(value);
    card.append(caption, content);
    container.appendChild(card);
  }

  const description = document.createElement("div");
  description.className = "summary-description";
  description.textContent = data.call_summary || "No summary was returned for this conversation.";
  container.appendChild(description);
}

$("end").onclick = async () => {
  active = false;
  busy = false;

  try {
    if (rec) rec.abort();
  } catch {}

  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }

  endUi();

  $("summaryBox").hidden = false;
  $("summary").textContent = "Generating summary…";

  try {
    const response = await fetch("/api/summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transcript: history,
        tool_events: toolEvents
      })
    });

    if (!response.ok) throw new Error("Summary request failed");

    const summary = await response.json();
    renderSummary(summary);
  } catch {
    $("summary").textContent =
      "Summary unavailable. The transcript above has been preserved.";
  }
};

$("typed").onsubmit = (event) => {
  event.preventDefault();

  const text = $("typedInput").value.trim();

  if (text && active && !busy) {
    $("typedInput").value = "";

    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }

    handleUser(text);
  }
};

function resetConvo(clearServer = true) {
  history = [];
  toolEvents = [];

  $("transcript").innerHTML = "";
  $("summaryBox").hidden = true;
  notice("");

  if (clearServer) {
    fetch("/api/reset", { method: "POST" })
      .then(loadOrders)
      .catch(() => notice("Could not reset the mock orders."));
  }
}

$("reset").onclick = () => {
  active = false;
  busy = false;

  try {
    if (rec) rec.abort();
  } catch {}

  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }

  endUi();
  resetConvo(false);
};

// ---------- Test orders ----------

async function loadOrders() {
  try {
    const response = await fetch("/api/orders");

    if (!response.ok) throw new Error("Could not load orders");

    const list = await response.json();
    const container = $("orders");

    container.replaceChildren();

    for (const order of list) {
      const card = document.createElement("div");
      card.className = "order";

      const heading = document.createElement("div");
      heading.className = "order-heading";
      const title = document.createElement("strong");
      title.textContent = order.id;
      heading.appendChild(title);

      const status = document.createElement("span");
      status.className = "order-status";
      const normalizedStatus = String(order.status || "").toLowerCase();
      if (normalizedStatus.includes("deliver")) status.classList.add("delivered");
      if (normalizedStatus.includes("process")) status.classList.add("processing");
      status.textContent = order.status || "Status unavailable";
      heading.appendChild(status);

      const details = document.createElement("div");
      details.className = "order-details";
      const lines = [
        order.customer,
        order.product,
        `₹${order.value}`,
        order.courier && order.tracking ? `${order.courier} — ${order.tracking}` : "",
        order.eta || "",
        order.delivered_days_ago ? `Delivered ${order.delivered_days_ago} days ago` : "",
        order.ordered_hours_ago ? `Ordered ${order.ordered_hours_ago} hours ago` : ""
      ].filter(Boolean);

      for (const line of lines) {
        const lineEl = document.createElement("span");
        lineEl.textContent = line;
        details.appendChild(lineEl);
      }

      card.append(heading, details);
      container.appendChild(card);
    }
  } catch (error) {
    console.error("Loading orders failed:", error);
    $("orders").textContent = "Could not load orders.";
  }
}

loadOrders();
