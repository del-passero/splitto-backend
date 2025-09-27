# src/routers/group_invites.py
import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { acceptGroupInvite, previewGroupInvite, type InvitePreview } from "../api/groupInvitesApi"

/* i18n */
type Lang = "ru" | "en" | "es"
const STRINGS: Record<Lang, Record<string, string>> = {
  en: {
    invitedYou: "invited you to the group",
    close: "Close",
    join: "Join group",
    joining: "Joining...",
    inviteError: "Invite error",
    acceptFailed: "Failed to accept invite",
    invalidInvite: "This invite link is invalid or expired.",
    goHome: "Go to Home",
  },
  ru: {
    invitedYou: "пригласил(а) вас в группу",
    close: "Закрыть",
    join: "Вступить в группу",
    joining: "Вступаем...",
    inviteError: "Ошибка приглашения",
    acceptFailed: "Не удалось принять приглашение",
    invalidInvite: "Ссылка приглашения недействительна или устарела.",
    goHome: "На главную",
  },
  es: {
    invitedYou: "te invitó al grupo",
    close: "Cerrar",
    join: "Unirse al grupo",
    joining: "Uniéndose...",
    inviteError: "Error de invitación",
    acceptFailed: "No se pudo aceptar la invitación",
    invalidInvite: "Este enlace de invitación no es válido o expiró.",
    goHome: "Ir al inicio",
  },
}
const normalizeLang = (c?: string | null): Lang => {
  const x = (c || "").toLowerCase().split("-")[0]
  return (["ru", "en", "es"].includes(x) ? x : "en") as Lang
}
const getLang = (): Lang => {
  const tg: any = (window as any)?.Telegram?.WebApp
  return normalizeLang(tg?.initDataUnsafe?.user?.language_code || tg?.initDataUnsafe?.language || tg?.languageCode)
}
const useT = () => {
  const lang = getLang()
  return (k: keyof typeof STRINGS["en"]) => STRINGS[lang][k] || STRINGS.en[k]
}

/* token helpers */
function getStartParam(): string | null {
  const tg: any = (window as any)?.Telegram?.WebApp
  const fromTg =
    (tg?.initDataUnsafe?.start_param as string | undefined) ??
    (tg?.initDataUnsafe?.startParam as string | undefined) ??
    null
  const params = new URLSearchParams(window.location.search)
  const fromUrl = params.get("startapp") || params.get("start") || params.get("tgWebAppStartParam") || null
  return fromTg || fromUrl
}
function normalizeToken(raw?: string | null): string | null {
  if (!raw) return null
  let t = String(raw).trim()
  try { t = decodeURIComponent(t) } catch {}
  const lower = t.toLowerCase()
  if (lower.startsWith("join:")) t = t.slice(5)
  if (lower.startsWith("g:")) t = t.slice(2)
  if (/^token=/.test(t)) t = t.replace(/^token=/, "")
  return t || null
}

/* theming */
function useOverlayColor() {
  const tg = (window as any)?.Telegram?.WebApp
  const scheme = tg?.colorScheme as "light" | "dark" | undefined
  return scheme === "dark" ? "rgba(0,0,0,0.6)" : "rgba(0,0,0,0.45)"
}

/* state */
type State =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "hidden" }
  | { status: "ready"; preview: InvitePreview; token?: string | null }
  | { status: "joining"; preview: InvitePreview; token?: string | null }
  | { status: "invalid"; reason?: string } // показываем причину
  | { status: "error"; message: string }

export default function InviteJoinModal() {
  const t = useT()
  const navigate = useNavigate()
  const [state, setState] = useState<State>({ status: "idle" })
  const overlayColor = useOverlayColor()

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setState({ status: "loading" })
      const token = normalizeToken(getStartParam())

      if (!token) {
        setState({ status: "invalid", reason: "missing_token" })
        return
      }

      try {
        const preview = await previewGroupInvite(token)
        if (cancelled) return

        if (!preview?.group?.id) {
          setState({ status: "invalid", reason: "group_not_found" })
          return
        }
        if (preview.already_member) {
          navigate(`/groups/${preview.group.id}`, { replace: true })
          setState({ status: "hidden" })
          return
        }
        setState({ status: "ready", preview, token })
      } catch (e: any) {
        // e.message содержит detail.code из бэка: bad_prefix, bad_signature, bad_token, ...
        setState({ status: "invalid", reason: e?.message || "bad_token" })
        console.warn("invite preview failed:", e?.message)
      }
    })()
    return () => { cancelled = true }
  }, [navigate])

  if (state.status === "hidden" || state.status === "idle" || state.status === "loading") return null

  if (state.status === "invalid") {
    const cardStyle: React.CSSProperties = {
      background: "var(--tg-theme-bg-color,#fff)",
      color: "var(--tg-theme-text-color,#111)",
      border: "1px solid var(--tg-theme-secondary-bg-color,rgba(0,0,0,0.06))",
      boxShadow: "0 8px 28px rgba(0,0,0,0.12)",
    }
    const hintStyle: React.CSSProperties = {
      color: "var(--tg-theme-hint-color,rgba(0,0,0,0.6))",
    }
    const secondaryBtnStyle: React.CSSProperties = {
      background: "var(--tg-theme-secondary-bg-color,rgba(0,0,0,0.05))",
      color: "var(--tg-theme-text-color,#111)",
    }
    const debug = state.reason ? `\n\n(code: ${state.reason})` : ""
    return (
      <div role="dialog" aria-modal="true" className="fixed inset-0 z-[9999] flex items-center justify-center" style={{ background: overlayColor }}>
        <div className="w-[92%] max-w-[460px] rounded-2xl p-5" style={cardStyle}>
          <div className="text-base mb-2" style={{ fontWeight: 600 }}>Invite</div>
          <div className="text-sm whitespace-pre-line" style={hintStyle}>
            {t("invalidInvite")}{debug}
          </div>
          <div className="flex gap-8 justify-end mt-6">
            <button
              onClick={() => navigate("/", { replace: true })}
              className="px-4 py-2 rounded-xl"
              style={secondaryBtnStyle}
            >
              {t("goHome")}
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (state.status === "error") return null

  const { preview, token } =
    state.status === "ready" || state.status === "joining" ? state : ({ preview: null, token: null } as any)
  const inviter = preview?.inviter
  const group = preview?.group
  const joining = state.status === "joining"

  const inviterTitle = useMemo(() => {
    const name = inviter?.name || ""
    const username = inviter?.username ? ` @${inviter.username}` : ""
    return `${name}${username}`.trim()
  }, [inviter])

  const onClose = () => {
    setState({ status: "hidden" })
    navigate("/", { replace: true })
  }

  const onJoin = async () => {
    if (!group?.id) return onClose()
    try {
      setState({ status: "joining", preview, token })
      const res = await acceptGroupInvite(token ?? undefined)
      if (res?.success && res?.group_id) {
        navigate(`/groups/${res.group_id}`, { replace: true })
        setState({ status: "hidden" })
      } else {
        setState({ status: "error", message: t("acceptFailed") })
        ;(window as any)?.Telegram?.WebApp?.showPopup?.({
          title: t("inviteError"),
          message: t("acceptFailed"),
          buttons: [{ type: "close" }],
        })
        navigate("/", { replace: true })
      }
    } catch {
      setState({ status: "error", message: t("acceptFailed") })
      ;(window as any)?.Telegram?.WebApp?.showPopup?.({
        title: t("inviteError"),
        message: t("acceptFailed"),
        buttons: [{ type: "close" }],
      })
      navigate("/", { replace: true })
    }
  }

  const cardStyle: React.CSSProperties = {
    background: "var(--tg-theme-bg-color,#fff)",
    color: "var(--tg-theme-text-color,#111)",
    border: "1px solid var(--tg-theme-secondary-bg-color,rgba(0,0,0,0.06))",
    boxShadow: "0 8px 28px rgba(0,0,0,0.12)",
  }
  const hintStyle: React.CSSProperties = {
    color: "var(--tg-theme-hint-color,rgba(0,0,0,0.6))",
  }
  const secondaryBtnStyle: React.CSSProperties = {
    background: "var(--tg-theme-secondary-bg-color,rgba(0,0,0,0.05))",
    color: "var(--tg-theme-text-color,#111)",
  }
  const primaryBtnStyle: React.CSSProperties = {
    background: "var(--tg-theme-button-color,#2ea6ff)",
    color: "var(--tg-theme-button-text-color,#fff)",
  }

  return (
    <div role="dialog" aria-modal="true" className="fixed inset-0 z-[9999] flex items-center justify-center" style={{ background: overlayColor }}>
      <div className="w-[92%] max-w-[460px] rounded-2xl p-5" style={cardStyle}>
        {/* Inviter */}
        <div className="flex items-center gap-3 mb-3">
          {inviter?.photo_url ? (
            <img src={inviter.photo_url} alt="" className="w-12 h-12 rounded-full object-cover" loading="lazy" referrerPolicy="no-referrer" />
          ) : (
            <div className="w-12 h-12 rounded-full" style={{ background: "rgba(0,0,0,0.08)" }} />
          )}
          <div className="text-sm" style={hintStyle}>{t("invitedYou")}</div>
        </div>

        {/* Group */}
        <div className="flex items-center gap-3 mb-4">
          {group?.avatar_url ? (
            <img src={group.avatar_url} alt="" className="w-10 h-10 rounded-xl object-cover" loading="lazy" referrerPolicy="no-referrer" />
          ) : (
            <div className="w-10 h-10 rounded-xl" style={{ background: "rgba(0,0,0,0.06)" }} />
          )}
          <div className="flex flex-col">
            <div className="font-medium">{group?.name || `#${group?.id}`}</div>
            {inviterTitle && <div className="text-sm" style={hintStyle}>{inviterTitle}</div>}
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-8 justify-end mt-6">
          <button onClick={onClose} className="px-4 py-2 rounded-xl" style={secondaryBtnStyle} disabled={joining}>
            {t("close")}
          </button>
          <button onClick={onJoin} className="px-4 py-2 rounded-xl font-medium" style={primaryBtnStyle} disabled={joining}>
            {joining ? t("joining") : t("join")}
          </button>
        </div>
      </div>
    </div>
  )
}
