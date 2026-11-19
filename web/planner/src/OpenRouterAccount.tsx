import {useEffect, useRef, useState, useSyncExternalStore} from "react";
import {OpenRouterModels} from "./OpenRouterModels";
import type {Selection} from "./openrouter-session";
import {openrouter} from "./openrouter-session";

type Props = {
  ready: boolean;
  onChange: (fresh: boolean) => void;
  selectionBusy: boolean;
  onModelSettings: () => void;
  onModelSelect: (selection: Selection) => void;
};

export function OpenRouterAccount({onChange, ready, selectionBusy, onModelSettings, onModelSelect}: Props) {
  const account = useSyncExternalStore(openrouter.subscribe, openrouter.snapshot);
  const dialog = useRef<HTMLDialogElement>(null);
  const generation = useRef(0);
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const [replace, setReplace] = useState(false);
  const [opened, setOpened] = useState(false);
  const pending = account.state === "connecting";
  useEffect(() => {
    const clearInput = () => {if (input.current) input.current.value = "";};
    window.addEventListener("pagehide", clearInput);
    window.addEventListener("pageshow", clearInput);
    return () => {window.removeEventListener("pagehide", clearInput); window.removeEventListener("pageshow", clearInput);};
  }, []);
  useEffect(() => {if (input.current) input.current.value = "";}, [account.epoch]);
  useEffect(() => {if (replace) input.current?.focus();}, [replace]);
  return <>
    <button className="account-trigger" type="button" disabled={!ready} onClick={() => {setError(""); setReplace(false); setOpened(true); dialog.current?.showModal();}}>
      OpenRouter <span>{account.state === "connected" ? "Connected" : account.connectionId ? "Reconnect to resume" : "Connect account"}</span>
    </button>
    <dialog ref={dialog} className="openrouter-account" aria-labelledby="openrouter-account-title" onClose={() => {setOpened(false); if (input.current) input.current.value = "";}}>
      <div className="account-heading"><h2 id="openrouter-account-title">OpenRouter account</h2>
        <button type="button" autoFocus aria-label="Close OpenRouter account" onClick={() => dialog.current?.close()}>×</button></div>
      <p>Connect your OpenRouter key to choose a model and talk to the campaign agent.</p>
      <p className="revision">The selected campaign context is sent to OpenRouter and the inference provider. No-training routing; safety retention may apply. This is not a zero-retention or residency promise.</p>
      <p role="status">{account.state === "connected" ? "Connected in this tab" : pending ? "Checking connection…" : account.state === "expired" ? "Connection expired" : account.connectionId ? "Reconnect to resume the original operation" : "Disconnected"}</p>
      {account.expiresAt && <p className="revision">Connection expires {new Date(account.expiresAt * 1000).toLocaleTimeString()}. Reloading or leaving this page clears the key.</p>}
      {(account.state !== "connected" || replace) && <form autoComplete="off" onSubmit={event => {
        event.preventDefault();
        if (!input.current || pending) return;
        setError("");
        const attempt = ++generation.current;
        onChange(replace || !account.connectionId);
        void openrouter.connect(input.current, replace).then(() => {if (attempt === generation.current) setReplace(false);}).catch(failure => {if (attempt === generation.current) setError(failure.message);});
      }}>
        <label htmlFor="openrouter-key">{replace ? "Replacement OpenRouter key" : account.connectionId ? "Original OpenRouter key" : "OpenRouter key"}</label>
        <input ref={input} id="openrouter-key" type="password" autoComplete="off" autoCapitalize="none" spellCheck={false} maxLength={512} disabled={pending} required />
        <p className="revision">Held only in this tab's active memory. The field clears immediately on submit. Use a provider spend limit as well as the app's local budget.</p>
        <button disabled={pending}>{pending ? "Connecting…" : replace ? "Replace key and connect" : account.connectionId ? "Reconnect original key" : "Connect OpenRouter"}</button>
      </form>}
      {account.connectionId && !pending && !replace && <button type="button" onClick={() => {
        generation.current++; openrouter.clear(); onChange(true); setReplace(true); setError(""); input.current?.focus();
      }}>Replace key</button>}
      {account.connectionId && <button type="button" onClick={() => {
        generation.current++; if (input.current) input.current.value = "";
        onChange(true); setReplace(false); setError("");
        void openrouter.disconnect().catch(() => setError("The key was cleared in this tab. Server disconnect could not be confirmed; sign out to revoke the session."));
      }}>Disconnect</button>}
      {error && <p className="error" role="alert">{error}</p>}
      {opened && account.state === "connected" && !replace && <OpenRouterModels disabled={selectionBusy}
        onSettingsChange={onModelSettings} onSelect={onModelSelect} />}
      <p className="revision">Disconnect, replacement, expiry, sign-out or a workspace change clears the active key. Already sent requests may still complete; saved usage and history remain available.</p>
    </dialog>
  </>;
}
