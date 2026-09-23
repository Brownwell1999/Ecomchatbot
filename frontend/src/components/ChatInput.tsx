import { useState, type FormEvent, type KeyboardEvent } from "react";

const MAX_CHARS = 2000;

interface Props {
  onSend: (text: string) => void;
  disabled: boolean;
}

export function ChatInput({ onSend, disabled }: Props) {
  const [text, setText] = useState("");
  const tooLong = text.length > MAX_CHARS;
  const canSend = !disabled && text.trim().length > 0 && !tooLong;

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!canSend) return;
    onSend(text);
    setText("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <form className="chat-input" onSubmit={submit} data-testid="chat-form">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Ask about products, orders, returns…"
        rows={1}
        aria-label="Message"
        data-testid="chat-input"
      />
      <button type="submit" className="btn-send" disabled={!canSend} data-testid="send-button" aria-label="Send">
        ➤
      </button>
      {text.length > MAX_CHARS * 0.8 && (
        <span className={`char-count ${tooLong ? "over" : ""}`} data-testid="char-count">
          {text.length}/{MAX_CHARS}
        </span>
      )}
    </form>
  );
}
