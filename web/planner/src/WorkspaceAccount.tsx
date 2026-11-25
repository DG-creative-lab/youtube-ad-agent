import {useId} from "react";
import type {Selection} from "./openrouter-session";
import {OpenRouterAccount} from "./OpenRouterAccount";

type Props = {
  name: string;
  initials: string;
  workspace: string;
  preview: boolean;
  providerAvailable: boolean;
  providerReady: boolean;
  onProviderChange: (fresh: boolean) => void;
  selectionBusy: boolean;
  onModelSettings: () => void;
  onModelSelect: (selection: Selection) => void;
};

export function WorkspaceAccount({name, initials, workspace, preview, providerAvailable, providerReady, onProviderChange, selectionBusy, onModelSettings, onModelSelect}: Props) {
  const menuId = useId();
  const identity = <>
    <span className="operator-avatar" aria-hidden="true">{initials}</span>
    <span>{name}<small>{workspace}</small></span>
  </>;
  if (!preview && !providerAvailable) return <div className="operator-identity">{identity}</div>;
  return <>
    <button type="button" className="operator-identity operator-trigger" popoverTarget={menuId} aria-label={`${name} account`}>
      {identity}<span className="operator-caret" aria-hidden="true">⌄</span>
    </button>
    <section id={menuId} popover="auto" className="workspace-account" aria-label="Workspace account">
      {preview && <a href="/invite">Manage invite</a>}
      {providerAvailable && <OpenRouterAccount ready={providerReady} onChange={onProviderChange} selectionBusy={selectionBusy} onModelSettings={onModelSettings} onModelSelect={onModelSelect} />}
    </section>
  </>;
}
