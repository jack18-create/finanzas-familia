import streamlit as st
import pandas as pd
import json

from db import (
    init_db, ensure_users, load_templates_from_yaml, ensure_budgets_for_month,
    list_budgets, sum_contribs_by_user, add_income, incomes_for_user,
    current_month, month_name
)
from utils import fmt_clp, proportional_allocate, progress_of_row

# --- Inicialización de datos/mes ---
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
#  Registrar y distribuir
# =======================
with st.expander("➕ Registrar ingreso y distribuir automáticamente", expanded=True):
    col1, col2, col3 = st.columns([2, 1, 2])
    with col1:
        amount = st.number_input(
            "Monto recibido (CLP). Puede ser sueldo, quincena o cualquier ingreso.",
            min_value=0, step=1000, value=0
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
        jack_pct   = float(shares.get("Jack", 50)) / 100.0
        jasmin_pct = float(shares.get("Jasmin", 50)) / 100.0

        # Topes individuales
        tope_jack   = int(limit_total * jack_pct)
        tope_jasmin = int(limit_total * jasmin_pct)

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
