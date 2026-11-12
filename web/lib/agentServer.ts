// Server-side LLM bridge. Conversation is kept in Gemini "contents" format by the client;
// model parts (including any thought signatures) are passed back verbatim.

export type Part = { text?: string; functionCall?: { name: string; args?: Record<string, unknown>; id?: string };
  functionResponse?: { name: string; response: unknown; id?: string }; [k: string]: unknown };
export type Content = { role: "user" | "model"; parts: Part[] };

export const SYSTEM = `You are Kunci, the operations agent for Kedai Runcit Maju Sdn Bhd, a small Malaysian grocery wholesaler (fictional demo company).
You answer the owner's questions about invoices, overdue payments and payroll aggregates by calling the fetch_ledger tool.
The ledger API needs a bearer credential. You never see, request or repeat that credential: it is split across five custodians with SAKSI secret sharing and is reassembled inside the user's browser only for the instant of the API call. If a tool result says the credential is unavailable or a custodian was rejected, explain that plainly and do not retry more than once.
Answer in the language of the question (English or Bahasa Malaysia), concisely, with amounts in RM. Use at most 3 tool calls per question.`;

export const TOOLS = [
  {
    name: "fetch_ledger",
    description:
      "Call the company's ledger API. The credential is attached by the browser after SAKSI validates the custodians' shares; you do not provide it.",
    parameters: {
      type: "object",
      properties: {
        endpoint: { type: "string", enum: ["health", "invoices", "overdue", "payroll_summary"],
          description: "invoices: one month's invoices and total; overdue: unpaid invoices past due; payroll_summary: aggregates; health: service status" },
        month: { type: "string", description: "YYYY-MM, for invoices or payroll_summary (data exists for 2026-09 and 2026-10)" },
      },
      required: ["endpoint"],
    },
  },
];

export async function callGemini(contents: Content[]): Promise<{ content: Content; model: string }> {
  const key = process.env.GEMINI_API_KEY;
  if (!key) throw new Error("no-gemini-key");
  const models = (process.env.GEMINI_MODEL ||
    "gemini-3-flash-preview,gemini-flash-latest,gemini-3-flash,gemini-2.5-flash,gemini-flash-lite-latest,gemini-2.5-flash-lite")
    .split(",").map((s) => s.trim()).filter(Boolean);
  let last = "";
  for (const model of models) {
    let r: Response;
    try {
      r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`, {
      signal: AbortSignal.timeout(18_000),
      method: "POST",
      headers: { "Content-Type": "application/json", "x-goog-api-key": key },
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: SYSTEM }] },
        contents,
        tools: [{ functionDeclarations: TOOLS }],
        generationConfig: { temperature: 0.2, maxOutputTokens: 1024 },
      }),
      });
    } catch (e) {
      last = `${model}: ${(e as Error).name}`;
      continue; // timeout or network error: try the next model
    }
    // Retired model (404), overloaded (503/500) or rate-limited (429): try the next model.
    if ([404, 429, 500, 503].includes(r.status)) { last = `${model}: ${r.status}`; continue; }
    if (!r.ok) throw new Error(`gemini ${model} ${r.status}: ${(await r.text()).slice(0, 300)}`);
    const j = await r.json();
    const content = j?.candidates?.[0]?.content as Content | undefined;
    if (!content?.parts?.length) throw new Error(`gemini ${model}: empty response`);
    content.role = "model";
    return { content, model };
  }
  throw new Error(`gemini: no available model (${last})`);
}

// Groq (OpenAI-compatible) fallback; converts to/from Gemini-style contents.
export async function callGroq(contents: Content[]): Promise<{ content: Content; model: string }> {
  const key = process.env.GROQ_API_KEY;
  if (!key) throw new Error("no-groq-key");
  const model = process.env.GROQ_MODEL || "llama-3.3-70b-versatile";
  const messages: Record<string, unknown>[] = [{ role: "system", content: SYSTEM }];
  let callNo = 0;
  const pending: string[] = [];
  for (const c of contents) {
    if (c.role === "model") {
      const calls = c.parts.filter((p) => p.functionCall);
      const text = c.parts.map((p) => p.text).filter(Boolean).join("\n");
      if (calls.length) {
        const tool_calls = calls.map((p) => {
          const id = `call_${callNo++}`;
          pending.push(id);
          return { id, type: "function", function: { name: p.functionCall!.name, arguments: JSON.stringify(p.functionCall!.args || {}) } };
        });
        messages.push({ role: "assistant", content: text || null, tool_calls });
      } else messages.push({ role: "assistant", content: text });
    } else {
      for (const p of c.parts) {
        if (p.functionResponse) messages.push({ role: "tool", tool_call_id: pending.shift() || `call_${callNo++}`, content: JSON.stringify(p.functionResponse.response) });
        else if (p.text) messages.push({ role: "user", content: p.text });
      }
    }
  }
  const r = await fetch("https://api.groq.com/openai/v1/chat/completions", {
    signal: AbortSignal.timeout(20_000),
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
    body: JSON.stringify({ model, messages, temperature: 0.2, max_tokens: 1024,
      tools: TOOLS.map((t) => ({ type: "function", function: t })) }),
  });
  if (!r.ok) throw new Error(`groq ${r.status}: ${(await r.text()).slice(0, 300)}`);
  const j = await r.json();
  const msg = j?.choices?.[0]?.message;
  const parts: Part[] = [];
  if (msg?.content) parts.push({ text: msg.content });
  for (const tc of msg?.tool_calls || []) {
    let args = {};
    try { args = JSON.parse(tc.function.arguments || "{}"); } catch { /* keep empty */ }
    parts.push({ functionCall: { name: tc.function.name, args } });
  }
  if (!parts.length) parts.push({ text: "" });
  return { content: { role: "model", parts }, model };
}
