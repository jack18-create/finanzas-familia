# 💸 Finanzas Familiares (Streamlit + Python)

App para administrar el dinero entre **Jack** y **Jasmin**:

- Categorías compartidas e individuales
- Distribución automática de sueldo/quincena (proporcional a tus metas)
- Límite por categoría y estado **“GASTO LISTO”**
- Reinicio automático por **mes**
- Visibilidad: ambos ven **compartidos**; cada uno ve solo sus **categorías personales**

## Estructura
```
finanzas_familia_streamlit/
├── app.py
├── budgets.yaml
├── budget.db            # se crea solo
├── db.py
├── utils.py
├── requirements.txt
└── .streamlit/
    └── secrets.toml.example
```

## Instalación (Mac)
```bash
# 1) Opcional: crear entorno
python3 -m venv .venv
source .venv/bin/activate

# 2) Instalar dependencias
pip install -r requirements.txt

# 3) Configurar contraseñas
mkdir -p .streamlit
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
open -e .streamlit/secrets.toml  # edita las claves

# 4) Ejecutar
streamlit run app.py
```

## Cómo usar
1. Inicia sesión (Jack/Jasmin).
2. Registra un ingreso (sueldo/quincena) y presiona **Distribuir ahora**.
3. Mira el **Resumen**: compartidos y tus categorías personales con su progreso.
4. En **Aportes manuales** puedes poner un monto específico a una categoría.
5. La app crea el mes actual automáticamente (o usa *Reiniciar / Crear mes nuevo*).

## Editar límites
`budgets.yaml` viene así por defecto:

- Compartidos (50/50): Arriendo 250.000, Comida 100.000, Emergencia 50.000, Internet 17.502
- Jack: Ahorro 200.000 · Ropa/calzado 100.000 · Paseos 100.000
- Jasmin: Ahorro 200.000 · Ropa/calzado 100.000 · Paseos 100.000 · Mandar hijo 100.000

Cambia montos o agrega categorías copiando el formato.

## Notas
- Los datos se guardan en `budget.db` (SQLite).
- Si quieres porcentajes distintos a 50/50, modifícalos en `budgets.yaml`.