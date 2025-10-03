# app.py
import streamlit as st
import pandas as pd
import json
import re

from db import (
    init_db, ensure_users, load_templates_from_yaml, ensure_budgets_for_month,
    list_budgets, sum_contribs_by_user, add_income, incomes_for_user,
    current_month, month_name
)
from utils import fmt_clp, proportional_allocate, progress_of_row

# =======================
#  Helpers
# =======================
def parse_money(s: str) -> int:
    """'$200.000', '200000', '200,000' -> 200000 (int)."""
    if not s:
        return 0
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else 0

def money_input(label: str, key: str, default: int = 0) -> int:
    """
    Input texto 'tipo moneda' que acepta $ y puntos.
    Muestra debajo el valor interpretado.
    """
    default_str = st.session_state.get(key + "_display", fmt_clp(default))
    s = st.text_input(label, value=default_str, key=key + "_display")
    val = parse_money(s)
    st.caption(f"Interpretado: **{fmt_clp(val)}**")
    return val

def share_to_fraction(v) -> float:
    """50 o '50%' -> 0.5 ; 0.5 -> 0.5 (default 0.5)."""
    try:
        if isinstance(v, str):
            v = v.strip().replace("%", "")
        val = float(v)
    except Exception:
        return 0.5
    return val if val <= 1 else (val / 100.0)

def build_plan_for_user(user: str, month: str):
    """
    Lista de categorías visibles con su capacidad restante (lo que falta
    para completar el tope personal este mes).
    """
    plan = []
    rows = list_budgets(month)  # (id, tkey, name, ctype, owner, limit_total, shares_json)
    for r in rows:
        b_id, tkey, name, ctype, owner, limit_total, shares_json = r
        if ctype == "shared" or (ctype == "individual" and owner == user):
            if ctype == "shared":
                try:
                    shares = json.loads(shares_json) if shares_json else {}
                except Exception:
                    shares = {}
                frac = share_to_fraction(shares.get(user, 50))
                personal_cap = int(round(limit_total * frac))
            else:
                personal_cap = int(limit_total)

            ya_aportado = sum_contribs_by_user(b_id, user)
            restante = max(0, personal_cap - ya_aportado)
            # Solo mostramos filas con algo que completar
            if restante > 0:
                plan.append({
                    "id": b_id,
                    "name": name + (" (comp.)" if ctype == "shared" else ""),
                    "cap_restante": restante,
                    "aportado_actual": ya_aportado,
                    "tope_personal": personal_cap
                })
    return plan

def suggest_by_capacity(capacities, total: int):
    """
    Distribución proporcional capada por capacidad. Devuelve lista de asignaciones
    y leftover (si el total supera la suma de capacidades).
    """
    if total <= 0 or not capacities:
        return [0]*len(capacities), total

    cap_total = sum(capacities)
    if cap_total == 0:
        return [0]*len(capacities), total

    raw = [total * c / cap_total for c in capacities]
    alloc = [min(int(round(x)), capacities[i]) for i, x in enumerate(raw)]

    diff = total - sum(alloc)
    i = 0
    while diff != 0 and i < 10000:
        for j in range(len(alloc)):
            if diff == 0:
                break
            if diff > 0 and alloc[j] < capacities[j]:
                alloc[j] += 1
                diff -= 1
            elif diff < 0 and alloc[j] > 0:
                alloc[j] -= 1
                diff += 1
        i += 1

    leftover = max(0, total - sum(alloc))
    return alloc, leftover

def rebalance_with_fixed(df: pd.DataFrame, total: int) -> pd.DataFrame:
    """
    - Respeta filas con Fijar=True
    - Recorta por Capacidad
    - Reparte el resto proporcional a Capacidad restante del resto
    """
    out = df.copy()
    out["Asignar"] = out[["Asignar", "Capacidad restante"]].min(axis=1).clip(lower=0).astype(int)

    fixed_mask = out["Fijar"] == True
    fixed_sum = int(out.loc[fixed_mask, "Asignar"].sum())

    if fixed_sum > total:
        # recortamos fijadas si se pasó del total (último recurso)
        factor = total / fixed_sum if fixed_sum else 0
        out.loc[fixed_mask, "Asignar"] = (out.loc[fixed_mask, "Asignar"] * factor).round().astype(int)
        fixed_sum = int(out.loc[fixed_mask, "Asignar"].sum())

    free_df = out.loc[~fixed_mask].copy()
    free_total_target = max(0, total - fixed_sum)

    if not free_df.empty:
        caps = free_df["Capacidad restante"].tolist()
        alloc, _ = suggest_by_capacity(caps, free_total_target)
        free_df["Asignar"] = alloc
        out = pd.concat([out.loc[fixed_mask], free_df], ignore_index=True)

    # ajuste final por redondeo
    delta = total - int(out["Asignar"].sum())
    if delta != 0 and not out.empty:
        # intentamos ajustar sobre filas no fijadas con margen
        order = out.index.tolist()
        for idx in order:
            if delta == 0:
                break
            cap = int(out.loc[idx, "Capacidad restante"])
            cur = int(out.loc[idx, "Asignar"])
            fij = bool(out.loc[idx, "Fijar"])
            if fij:
                continue
            if delta > 0 and cur < cap:
                out.loc[idx, "Asignar"] = cur + 1
                delta -= 1
            elif delta < 0 and cur > 0:
                out.loc[idx, "Asignar"] = cur - 1
                delta += 1
    return out

# =======================
#  App init
# =======================
init_db()
ensure_users()
load_templates_from_yaml()
ensure_budgets_for_month()

st.set_page_config(page_title="Finanzas Familia Jack & Jasmin", page_icon="💸", layout="wide")

# ---- Auth
st.sidebar.title("👤 Iniciar sesión")
usernames = ["Jack", "Jasmin"]
username = st.sidebar.selectbox("Usuario", usernames, index=0)
pwd = st.sidebar.text_input("Clave", type="password")

def auth_ok():
    try:
        creds = st.secrets["credentials"]
    except Exception:
        return True
    return username in creds and pwd == creds[username]

if not auth_ok():
    st.sidebar.info("Coloca tu clave. (Configura .streamlit/secrets.toml con tus contraseñas)")
    st.stop()

st.sidebar.success(f"Conectado como {username} ✅")
month = current_month()
st.sidebar.caption(f"Mes actual: **{month_name(month)}**")
if st.sidebar.button("🔄 Reiniciar / Crear mes nuevo"):
    ensure_budgets_for_month(month)
    st.sidebar.success("Mes verificado/creado.")

# =======================
#  Encabezado
# =======================
st.title("💸 Finanzas Familiares — Jack & Jasmin")
st.write("Registra ingresos, edita la distribución por categoría y aplica el aporte; el resto se rebalancea automáticamente.")

# =======================
#  Registrar ingreso (editable)
# =======================
with st.expander("➕ Registrar ingreso y distribuir (editable)", expanded=True):
    col1, col2, col3 = st.columns([2, 1, 2])
    with col1:
        ingreso_total = money_input("Monto a distribuir (CLP)", key="ingreso_total", default=0)
    with col2:
        tipo = st.selectbox("Tipo", ["Sueldo", "Quincena", "Otro"], index=1)
    with col3:
        nota = st.text_input("Nota (opcional)", value="")

    # Construimos plan y sugerencia
    plan = build_plan_for_user(username, month)

    if not plan:
        st.info("No hay categorías con capacidad disponible para este mes.")
    else:
        caps = [p["cap_restante"] for p in plan]
        sugerencia, _ = suggest_by_capacity(caps, ingreso_total)

        base_df = pd.DataFrame([{
            "ID": p["id"],
            "Categoría": p["name"],
            "Aportado actual": p["aportado_actual"],
            "Tope personal": p["tope_personal"],
            "Capacidad restante": p["cap_restante"],
            "Asignar": sugerencia[i],
            "Fijar": False
        } for i, p in enumerate(plan)])

        st.write("Edita **Asignar** (este ingreso) directamente en la tabla. Marca **Fijar** en las filas que no deben cambiar al rebalancear.")
        with st.form("edit_dist_form"):
            edited = st.data_editor(
                base_df,
                num_rows="fixed",
                hide_index=True,
                use_container_width=True,
                column_config={
                    "ID": st.column_config.TextColumn("ID", disabled=True),
                    "Categoría": st.column_config.TextColumn("Categoría", disabled=True),
                    "Aportado actual": st.column_config.TextColumn("Aportado actual", disabled=True),
                    "Tope personal": st.column_config.TextColumn("Tope personal", disabled=True),
                    "Capacidad restante": st.column_config.NumberColumn("Capacidad restante", disabled=True, format="%d"),
                    "Asignar": st.column_config.NumberColumn("Asignar", min_value=0, step=1000, format="%d"),
                    "Fijar": st.column_config.CheckboxColumn("Fijar"),
                },
            )

            c1, c2 = st.columns(2)
            with c1:
                rebalance_btn = st.form_submit_button("🔁 Rebalancear")
            with c2:
                aplicar_btn = st.form_submit_button("✔️ Aplicar")

        # Ejecutar rebalance / aplicar
        if rebalance_btn or aplicar_btn:
            if ingreso_total <= 0:
                st.warning("Ingresa un monto mayor que cero.")
            else:
                final_df = rebalance_with_fixed(edited, ingreso_total)
                total_final = int(final_df["Asignar"].sum())

                if rebalance_btn:
                    st.info(f"Rebalanceado a **{fmt_clp(total_final)}** (de {fmt_clp(ingreso_total)}). Puedes ajustar y volver a rebalancear.")
                    st.dataframe(
                        final_df[["Categoría", "Capacidad restante", "Asignar", "Fijar"]],
                        use_container_width=True, hide_index=True
                    )

                if aplicar_btn:
                    # Registrar ingreso + aportes
                    add_income(username, int(ingreso_total), f"{tipo} - Editado en tabla - {nota}".strip())
                    from db import add_contribution
                    applied = 0
                    for _, row in final_df.iterrows():
                        val = int(row["Asignar"])
                        if val > 0:
                            add_contribution(int(row["ID"]), username, val)
                            applied += 1
                    st.success(f"Aplicado: {applied} aportes por un total de {fmt_clp(total_final)}.")
                    if total_final < ingreso_total:
                        st.info(f"No se pudo asignar {fmt_clp(ingreso_total - total_final)} por falta de capacidad en las categorías.")
                    st.rerun()

# =======================
#  Tabs
# =======================
tabs = st.tabs(["📊 Resumen", "📜 Historial"])

# -------- Resumen --------
with tabs[0]:
    rows = list_budgets(month)
    shared_rows = [r for r in rows if r[3] == "shared"]
    my_rows     = [r for r in rows if (r[3] == "individual" and r[4] == username)]

    st.subheader("Gastos compartidos (visibles para ambos)")
    sdata = []
    for r in shared_rows:
        b_id, tkey, name, ctype, owner, limit_total, shares_json = r
        try:
            shares = json.loads(shares_json) if shares_json else {}
        except Exception:
            shares = {}

        jack_frac   = share_to_fraction(shares.get("Jack", 50))
        jasmin_frac = share_to_fraction(shares.get("Jasmin", 50))
        tope_jack   = int(round(limit_total * jack_frac))
        tope_jasmin = int(round(limit_total * jasmin_frac))

        ap_jack   = sum_contribs_by_user(b_id, "Jack")
        ap_jasmin = sum_contribs_by_user(b_id, "Jasmin")

        est_jack   = "✅ Listo" if ap_jack >= tope_jack else f"⏳ {fmt_clp(ap_jack)}/{fmt_clp(tope_jack)}"
        est_jasmin = "✅ Listo" if ap_jasmin >= tope_jasmin else f"⏳ {fmt_clp(ap_jasmin)}/{fmt_clp(tope_jasmin)}"

        total, pct, done = progress_of_row(r)
        est_general = "✅ GASTO LISTO" if done else "⏳ En progreso"

        sdata.append({
            "Categoría":       name,
            "Aportado Jack":   fmt_clp(ap_jack),
            "Tope Jack":       fmt_clp(tope_jack),
            "Estado Jack":     est_jack,
            "Aportado Jasmin": fmt_clp(ap_jasmin),
            "Tope Jasmin":     fmt_clp(tope_jasmin),
            "Estado Jasmin":   est_jasmin,
            "Aportado total":  fmt_clp(total),
            "Límite total":    fmt_clp(limit_total),
            "Estado general":  est_general,
        })

    if sdata:
        cols = [
            "Categoría",
            "Aportado Jack", "Tope Jack", "Estado Jack",
            "Aportado Jasmin", "Tope Jasmin", "Estado Jasmin",
            "Aportado total", "Límite total", "Estado general",
        ]
        sdf = pd.DataFrame(sdata)[cols]
        st.dataframe(sdf, use_container_width=True, hide_index=True)
    else:
        st.info("No hay categorías compartidas.")

    st.subheader(f"Tus categorías (solo {username})")
    pdata = []
    for r in my_rows:
        total_u = sum_contribs_by_user(r[0], username)
        total_cat, pct, done = progress_of_row(r)
        state = "✅ GASTO LISTO" if done else "⏳ En progreso"
        pdata.append({
            "Categoría":            r[2],
            "Tu aporte":            fmt_clp(total_u),
            "Límite (tu objetivo)": fmt_clp(r[5]),
            "Estado":               state
        })
    if pdata:
        pdf = pd.DataFrame(pdata)
        st.dataframe(pdf, use_container_width=True, hide_index=True)
    else:
        st.info("No tienes categorías personales configuradas.")

# -------- Historial --------
with tabs[1]:
    st.subheader("Tus últimos ingresos")
    rows = incomes_for_user(username, limit=50)
    if rows:
        df = pd.DataFrame([
            {"Monto": fmt_clp(a), "Fecha": ts.replace("T", " "), "Nota": (note or "")}
            for a, ts, note in rows
        ])
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Sin ingresos registrados aún.")

st.caption("Edita límites en budgets.yaml. Cada nuevo mes se crea automáticamente con los límites configurados.")






