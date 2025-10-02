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
#  Helpers de dinero y shares
# =======================
def parse_money(s: str) -> int:
    """Convierte '$200.000', '200000', '200,000' -> 200000 (int)."""
    if not s:
        return 0
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else 0

def money_input(label: str, key: str, default: int = 0) -> int:
    """
    Input de texto 'tipo moneda' que acepta $ y puntos.
    Muestra debajo el valor interpretado con formato CLP.
    """
    default_str = st.session_state.get(key + "_display", fmt_clp(default))
    s = st.text_input(label, value=default_str, key=key + "_display")
    val = parse_money(s)
    st.caption(f"Interpretado: **{fmt_clp(val)}**")
    return val

def share_to_fraction(v) -> float:
    """
    Acepta 50 o '50%' -> 0.5 ; acepta 0.5 -> 0.5.
    Si no se puede parsear, retorna 0.5.
    """
    try:
        if isinstance(v, str):
            v = v.strip().replace("%", "")
        val = float(v)
    except Exception:
        return 0.5
    return val if val <= 1 else (val / 100.0)

# =======================
#  Inicialización
# =======================
init_db()
ensure_users()
load_templates_from_yaml()
ensure_budgets_for_month()

st.set_page_config(page_title="Finanzas Familia Jack & Jasmin", page_icon="💸", layout="wide")

# =======================
#  Autenticación simple
# =======================
st.sidebar.title("👤 Iniciar sesión")
usernames = ["Jack", "Jasmin"]
username = st.sidebar.selectbox("Usuario", usernames, index=0)
pwd = st.sidebar.text_input("Clave", type="password")

def auth_ok():
    # Si no existe secrets, dejar pasar para pruebas
    try:
        creds = st.secrets["credentials"]
    except Exception:
        return True
    return username in creds and pwd == creds[username]

if not auth_ok():
    st.sidebar.info("Coloca tu clave. (Configura .streamlit/secrets.toml con tus contraseñas)")
    st.stop()

st.sidebar.success(f"Conectado como {username} ✅")

# Mes actual
month = current_month()
st.sidebar.caption(f"Mes actual: **{month_name(month)}**")

if st.sidebar.button("🔄 Reiniciar / Crear mes nuevo"):
    ensure_budgets_for_month(month)
    st.sidebar.success("Mes verificado/creado.")

# =======================
#  Encabezado
# =======================
st.title("💸 Finanzas Familiares — Jack & Jasmin")
st.write("Registra ingresos, distribuye automáticamente por categorías y sigue el progreso de cada gasto.")

# =======================
#  Registrar y distribuir (automático)
# =======================
with st.expander("➕ Registrar ingreso y distribuir automáticamente", expanded=True):
    col1, col2, col3 = st.columns([2, 1, 2])
    with col1:
        amount = money_input(
            "Monto recibido (CLP). Puede ser sueldo, quincena o cualquier ingreso.",
            key="ingreso_monto",
            default=0,
        )
    with col2:
        tipo = st.selectbox("Tipo", ["Sueldo", "Quincena", "Otro"], index=1)
    with col3:
        nota = st.text_input("Nota (opcional)", value="")

    if st.button("Distribuir ahora"):
        if amount <= 0:
            st.warning("Ingresa un monto mayor que cero.")
        else:
            add_income(username, int(amount), f"{tipo} - {nota}".strip())
            allocs, leftover = proportional_allocate(username, int(amount), month)
            if not allocs:
                st.info("No hay categorías con saldo pendiente para ti. No se hizo distribución.")
            else:
                df = pd.DataFrame([{
                    "Categoría": a["name"] if a["type"] == "individual" else f"{a['name']} (compartido)",
                    "Asignado": fmt_clp(a["allocated"])
                } for a in allocs])
                st.success("Ingreso registrado y distribuido por tus metas del mes.")
                st.dataframe(df, use_container_width=True)
                if leftover > 0:
                    st.info(f"Saldo no asignado (metas completas): **{fmt_clp(leftover)}**")

# =======================
#  Distribución editable con rebalance
# =======================
def build_plan_for_user(user: str, month: str):
    """
    Devuelve la lista de categorías visibles para el usuario con su capacidad
    restante (lo que falta para completar su tope personal este mes).
    """
    plan = []
    rows = list_budgets(month)  # (id, tkey, name, ctype, owner, limit_total, shares_json)
    for r in rows:
        b_id, tkey, name, ctype, owner, limit_total, shares_json = r

        # Solo veo compartidas y mis individuales
        if ctype == "shared" or (ctype == "individual" and owner == user):
            # tope personal
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
            if restante > 0:
                plan.append({
                    "id": b_id,
                    "name": name + (" (comp.)" if ctype == "shared" else ""),
                    "capacity": restante
                })
    return plan

def suggest_by_capacity(plan, total: int):
    """
    Sugerencia proporcional (capada por capacidad) para un total dado.
    Devuelve lista de ints y posible 'leftover' si ya no hay dónde poner.
    """
    if total <= 0 or not plan:
        return [0]*len(plan), total

    caps = [p["capacity"] for p in plan]
    cap_total = sum(caps)
    if cap_total == 0:
        return [0]*len(plan), total

    # Proporcional
    raw = [total * c / cap_total for c in caps]
    alloc = [min(int(round(x)), caps[i]) for i, x in enumerate(raw)]

    # Ajuste por redondeo/caps
    diff = total - sum(alloc)
    i = 0
    while diff != 0 and i < 10000:  # tope de seguridad
        for j in range(len(alloc)):
            if diff == 0:
                break
            if diff > 0 and alloc[j] < caps[j]:
                alloc[j] += 1
                diff -= 1
            elif diff < 0 and alloc[j] > 0:
                alloc[j] -= 1
                diff += 1
        i += 1

    leftover = max(0, total - sum(alloc))
    return alloc, leftover

with st.expander("✏️ Distribuir manualmente con rebalance", expanded=False):
    manual_total = money_input("Monto a distribuir (CLP)", key="manual_monto", default=0)
    tipo2 = st.selectbox("Tipo de ingreso", ["Sueldo", "Quincena", "Otro"], index=1, key="manual_tipo")
    nota2 = st.text_input("Nota (opcional)", value="", key="manual_nota")

    plan = build_plan_for_user(username, month)

    if not plan:
        st.info("No hay categorías con capacidad disponible para este mes.")
    else:
        # Sugerencia inicial
        sugg, _ = suggest_by_capacity(plan, manual_total)

        base_df = pd.DataFrame([{
            "ID": p["id"],
            "Categoría": p["name"],
            "Capacidad": p["capacity"],
            "Asignar": sugg[i],
            "Fijar": False
        } for i, p in enumerate(plan)])

        st.write("Marca **Fijar** en las filas que no quieres que cambien al rebalancear.")
        with st.form("manual_edit_form"):
            edit_df = st.data_editor(
                base_df,
                num_rows="fixed",
                hide_index=True,
                use_container_width=True,
                column_config={
                    "ID": st.column_config.TextColumn("ID", disabled=True),
                    "Capacidad": st.column_config.NumberColumn("Capacidad", disabled=True, format="%d"),
                    "Asignar": st.column_config.NumberColumn(
                        "Asignar", min_value=0, step=1000, format="%d",
                        help="Puedes escribir el monto. No debe superar la capacidad."
                    ),
                    "Fijar": st.column_config.CheckboxColumn("Fijar")
                },
            )
            submitted = st.form_submit_button("🔁 Rebalancear y aplicar")

        if submitted:
            if manual_total <= 0:
                st.warning("Ingresa un monto mayor que cero.")
                st.stop()

            # Limpia y recorta por capacidad
            edit_df["Asignar"] = edit_df[["Asignar", "Capacidad"]].min(axis=1)
            edit_df["Asignar"] = edit_df["Asignar"].clip(lower=0)

            # Suma de filas fijadas
            fixed_mask = edit_df["Fijar"] == True
            fixed_sum = int(edit_df.loc[fixed_mask, "Asignar"].sum())

            if fixed_sum > manual_total:
                st.error(
                    f"Las filas fijadas suman {fmt_clp(fixed_sum)}, que es mayor al total {fmt_clp(manual_total)}. "
                    "Baja algún valor o desmarca Fijar."
                )
                st.stop()

            # Repartir el resto entre las NO fijadas, proporcional a su capacidad restante
            free_df = edit_df.loc[~fixed_mask].copy()
            free_total_target = manual_total - fixed_sum

            # Si no hay libres, sólo se registran las fijadas
            if free_df.empty:
                final_df = edit_df.copy()
            else:
                caps = free_df["Capacidad"].tolist()
                alloc, leftover = suggest_by_capacity(
                    [{"capacity": c} for c in caps], free_total_target
                )
                free_df["Asignar"] = alloc
                final_df = pd.concat([edit_df.loc[fixed_mask], free_df], ignore_index=True)

            total_final = int(final_df["Asignar"].sum())

            # Registrar ingreso + aportes
            add_income(username, int(manual_total), f"{tipo2} - Manual editable - {nota2}".strip())
            from db import add_contribution
            applied_rows = 0
            for _, row in final_df.iterrows():
                val = int(row["Asignar"])
                if val > 0:
                    add_contribution(int(row["ID"]), username, val)
                    applied_rows += 1

            # Mostrar resultado
            shown = final_df.copy()
            shown["Asignar"] = shown["Asignar"].astype(int)
            st.success(f"Aplicado: {applied_rows} aportes por un total de {fmt_clp(total_final)}.")
            if total_final < manual_total:
                st.info(f"No se pudo asignar {fmt_clp(manual_total - total_final)} porque ya no quedaba capacidad en las categorías.")
            st.dataframe(
                shown[["Categoría", "Capacidad", "Asignar", "Fijar"]].sort_values("Categoría"),
                use_container_width=True, hide_index=True
            )

# =======================
#  Tabs
# =======================
tabs = st.tabs(["📊 Resumen", "🧾 Aportes manuales", "📜 Historial"])

# -------- Resumen --------
with tabs[0]:
    rows = list_budgets(month)
    # r = (b.id, template_key, t.name, t.ctype, t.owner, b.limit_total, t.shares_json)
    shared_rows = [r for r in rows if r[3] == "shared"]
    my_rows     = [r for r in rows if (r[3] == "individual" and r[4] == username)]

    # ==== Tabla con tope por persona en categorías compartidas ====
    st.subheader("Gastos compartidos (visibles para ambos)")

    sdata = []
    for r in shared_rows:
        b_id, tkey, name, ctype, owner, limit_total, shares_json = r

        # Porcentajes por persona desde budgets.yaml (por defecto 50/50)
        try:
            shares = json.loads(shares_json) if shares_json else {}
        except Exception:
            shares = {}

        jack_frac   = share_to_fraction(shares.get("Jack", 50))
        jasmin_frac = share_to_fraction(shares.get("Jasmin", 50))

        # Topes individuales
        tope_jack   = int(round(limit_total * jack_frac))
        tope_jasmin = int(round(limit_total * jasmin_frac))

        # Aportes realizados
        ap_jack   = sum_contribs_by_user(b_id, "Jack")
        ap_jasmin = sum_contribs_by_user(b_id, "Jasmin")

        # Estados individuales
        est_jack   = "✅ Listo" if ap_jack >= tope_jack else f"⏳ {fmt_clp(ap_jack)}/{fmt_clp(tope_jack)}"
        est_jasmin = "✅ Listo" if ap_jasmin >= tope_jasmin else f"⏳ {fmt_clp(ap_jasmin)}/{fmt_clp(tope_jasmin)}"

        # Estado general (como referencia global)
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

    # ==== Tus categorías individuales ====
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

# -------- Aportes manuales --------
with tabs[1]:
    st.subheader("Registrar aporte manual")
    rows = list_budgets(month)

    visible = []
    for r in rows:
        if r[3] == "shared":
            visible.append(r)
        elif r[3] == "individual" and r[4] == username:
            visible.append(r)

    if not visible:
        st.info("No hay categorías disponibles.")
    else:
        labels = [f"{r[2]} {'(compartido)' if r[3]=='shared' else ''}" for r in visible]
        selected = st.selectbox("Categoria", options=list(range(len(visible))), format_func=lambda i: labels[i])
        amt = st.number_input("Monto a aportar (CLP)", min_value=0, step=1000)

        if st.button("Agregar aporte"):
            from db import add_contribution
            add_contribution(visible[selected][0], username, int(amt))
            st.success("Aporte agregado.")

# -------- Historial de ingresos --------
with tabs[2]:
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




