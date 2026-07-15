import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import math
import unicodedata
import io
import os
from fpdf import FPDF
import plotly.express as px
import psycopg2
import warnings

warnings.filterwarnings('ignore', category=UserWarning)

# ==========================================
# 0. FUNCIONES DE UTILIDAD
# ==========================================
def get_guayaquil_time():
    tz = pytz.timezone('America/Guayaquil')
    return datetime.now(tz)

def clean_text(text):
    if not text: return ""
    text = str(text).upper()
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')

def format_date(dt): return dt.strftime("%d/%m/%Y")
def format_datetime(dt): return dt.strftime("%d/%m/%Y %H:%M:%S")

def parse_date(date_str):
    try: return datetime.strptime(date_str, "%d/%m/%Y")
    except ValueError: return datetime.strptime(date_str, "%d/%m/%Y %H:%M:%S")

# ==========================================
# 1. CONEXIÓN POSTGRESQL (NEON CLOUD)
# ==========================================
def get_db_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS socios (id SERIAL PRIMARY KEY, cedula TEXT UNIQUE, nombres TEXT, apellidos TEXT, telefono TEXT, correo TEXT, fecha_registro TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transacciones (id SERIAL PRIMARY KEY, socio_id INTEGER REFERENCES socios(id) ON DELETE CASCADE, tipo TEXT, monto REAL, fecha TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS prestamos (id SERIAL PRIMARY KEY, socio_id INTEGER REFERENCES socios(id) ON DELETE CASCADE, capital_original REAL, saldo_capital REAL, tipo_credito TEXT, estado TEXT, fecha_solicitud TEXT, fecha_otorgamiento TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pagos (id SERIAL PRIMARY KEY, prestamo_id INTEGER REFERENCES prestamos(id) ON DELETE CASCADE, pago_capital REAL, pago_interes REAL, fecha TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS flujo_extra (id SERIAL PRIMARY KEY, tipo TEXT, categoria TEXT, monto REAL, descripcion TEXT, fecha TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios (id SERIAL PRIMARY KEY, username TEXT UNIQUE, password TEXT, rol TEXT, socio_id INTEGER REFERENCES socios(id) ON DELETE CASCADE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bitacora (id SERIAL PRIMARY KEY, usuario TEXT, accion TEXT, detalle TEXT, fecha TEXT)''')
    
    c.execute("SELECT * FROM usuarios WHERE username='ADMIN'")
    if not c.fetchone():
        c.execute("INSERT INTO usuarios (username, password, rol) VALUES ('ADMIN', 'ADMIN', 'Administrador')")
    conn.commit()
    conn.close()

def run_query(query, params=(), returning=False):
    conn = get_db_connection()
    c = conn.cursor()
    query = query.replace('?', '%s')
    is_insert = query.strip().upper().startswith("INSERT")
    if is_insert and "RETURNING" not in query.upper():
        query += " RETURNING id"
    c.execute(query, params)
    
    if is_insert:
        inserted_id = c.fetchone()[0]
        conn.commit(); conn.close()
        return inserted_id
    if returning:
        result = c.fetchone()
        conn.commit(); conn.close()
        return result[0] if result else None
    conn.commit(); conn.close()
    return None

def fetch_data(query, params=()):
    conn = get_db_connection()
    c = conn.cursor()
    query = query.replace('?', '%s')
    c.execute(query, params)
    data = c.fetchall()
    conn.close()
    return data

def get_dataframe(query, params=()):
    conn = get_db_connection()
    query = query.replace('?', '%s')
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def registrar_bitacora(accion, detalle):
    usr = st.session_state.get('username', 'SISTEMA')
    fecha_hora = format_datetime(get_guayaquil_time())
    run_query("INSERT INTO bitacora (usuario, accion, detalle, fecha) VALUES (?,?,?,?)", (usr, clean_text(accion), clean_text(detalle), fecha_hora))

# ==========================================
# MOTOR DE REPORTES PDF 
# ==========================================
class BancoPDF(FPDF):
    def header(self):
        if os.path.exists('logo_banco.png'):
            self.image('logo_banco.png', 10, 8, w=28)
        self.set_y(15)
        self.set_font('Arial', 'B', 20)
        self.set_text_color(31, 78, 120)
        self.cell(0, 10, clean_text("Banco de la Familia Guzman"), ln=True, align='C')
        self.set_draw_color(31, 78, 120)
        self.set_line_width(0.8)
        self.line(10, 42, 200, 42)
        self.set_y(47)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f'Documento Oficial Generado por el Sistema - Pagina {self.page_no()}', 0, 0, 'C')

def generar_comprobante(titulo, num_ref, socio_nombre, detalles):
    pdf = BancoPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14); pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 10, clean_text(titulo), ln=True, align='C')
    pdf.set_font("Arial", '', 10); pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, f"REF: {num_ref}   |   FECHA DE EMISION: {format_datetime(get_guayaquil_time())}", ln=True, align='C')
    pdf.ln(10)
    pdf.set_fill_color(244, 248, 251); pdf.set_draw_color(31, 78, 120)
    pdf.rect(10, pdf.get_y(), 190, 12, 'DF')
    pdf.set_xy(15, pdf.get_y() + 2)
    pdf.set_font("Arial", 'B', 11); pdf.set_text_color(31, 78, 120)
    pdf.cell(0, 8, f"SOCIO / CLIENTE: {clean_text(socio_nombre)}", ln=True); pdf.ln(8)
    for key, val in detalles.items():
        pdf.set_font("Arial", 'B', 10); pdf.set_text_color(80, 80, 80)
        pdf.cell(60, 10, f"{key}:", border=0)
        if "TOTAL" in key or "ESTADO" in key or "PENDIENTE" in key:
            pdf.set_font("Arial", 'B', 11); pdf.set_text_color(31, 78, 120)
        else:
            pdf.set_font("Arial", '', 11); pdf.set_text_color(51, 51, 51)
        pdf.cell(0, 10, str(val), border=0, ln=True)
    try: return pdf.output(dest='S').encode('latin1')
    except: return bytes(pdf.output())

# ==========================================
# INICIALIZACIÓN Y CONFIGURACIÓN PÁGINA
# ==========================================
st.set_page_config(page_title="Banco Familiar", layout="wide", page_icon="🏦")

if 'db_initialized' not in st.session_state:
    try:
        init_db()
        st.session_state['db_initialized'] = True
    except Exception as e:
        st.error(f"Falla de conexión con la base de datos Neon. Verifica tus Secrets: {e}")
        st.stop()

if 'logged_in' not in st.session_state:
    st.session_state.update({'logged_in': False, 'username': None, 'rol': None, 'socio_id': None})

# ==========================================
# DISEÑO INTERACTIVO DE LOGIN Y RECUPERACIÓN
# ==========================================
if not st.session_state['logged_in']:
    st.markdown("""
    <style>
        .stApp {
            background: linear-gradient(135deg, #091D3E 0%, #030B18 100%) !important;
        }
        header { display: none !important; }
        
        div[data-testid="stForm"] {
            background-color: #F8F5EE !important;
            padding: 25px 20px 15px 20px !important;
            border-radius: 15px !important;
            box-shadow: 0px 10px 30px rgba(0,0,0,0.6) !important;
            border: none !important;
        }
        
        div[data-testid="stForm"] p, div[data-testid="stForm"] label, div[data-testid="stForm"] div {
            color: #091D3E !important;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif !important;
        }
        
        div[data-testid="stForm"] .stTextInput {
            margin-bottom: -10px !important;
        }
        
        input {
            background-color: #FFFFFF !important;
            border: 1px solid #D6D2C4 !important;
            border-radius: 6px !important;
            color: #091D3E !important;
            padding-left: 10px !important;
            font-size: 14px !important;
        }

        /* BOTÓN PRIMARIO (Iniciar Sesión / Guardar) */
        button[kind="primaryFormSubmit"], button[kind="primary"] {
            background-color: #122B4D !important;
            color: #FFFFFF !important;
            border: none !important;
            border-radius: 6px !important;
            padding: 6px 0px !important;
            font-weight: bold !important;
            font-size: 15px !important;
            width: 100% !important;
            margin-top: 5px !important;
        }
        button[kind="primaryFormSubmit"]:hover, button[kind="primary"]:hover {
            background-color: #1C447A !important;
        }
        
        /* BOTÓN SECUNDARIO INVISIBLE (Recuperar clave / Volver) */
        button[kind="secondaryFormSubmit"], button[kind="secondary"] {
            background-color: transparent !important;
            color: #1A5632 !important;
            border: none !important;
            box-shadow: none !important;
            padding: 0px !important;
            font-size: 12px !important;
            width: 100% !important;
            margin-top: 2px !important;
            min-height: 20px !important;
        }
        button[kind="secondaryFormSubmit"]:hover, button[kind="secondary"]:hover {
            text-decoration: underline !important;
            color: #122B4D !important;
            background-color: transparent !important;
        }
    </style>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1.5, 1, 1.5])
    
    with col2:
        # PANTALLA DE RECUPERACIÓN DE CONTRASEÑA
        if st.session_state.get('show_reset', False):
            with st.form("reset_form"):
                st.markdown("<h3 style='text-align: center; color: #091D3E !important; margin-top: 0; margin-bottom: 5px;'>🔄 Nueva Contraseña</h3>", unsafe_allow_html=True)
                st.markdown("<p style='text-align: center; font-size: 13px; line-height: 1.2;'>Solo disponible para <b>Socios</b> registrados. Ingrese su cédula para validar su identidad.</p>", unsafe_allow_html=True)
                
                ced_input = st.text_input("👤 Número de Cédula")
                pwd_new = st.text_input("🔒 Escriba su Nueva Contraseña", type="password")
                
                btn_save = st.form_submit_button("Guardar Nueva Contraseña", type="primary")
                btn_back = st.form_submit_button("⬅️ Volver al Inicio de Sesión", type="secondary")
                
                if btn_back:
                    st.session_state['show_reset'] = False
                    st.rerun()
                    
                if btn_save:
                    c_ced = clean_text(ced_input)
                    c_pwd = clean_text(pwd_new)
                    
                    if c_ced and c_pwd:
                        # Se busca ESTRICTAMENTE si la cédula existe y si su rol es SOCIO
                        user_data = fetch_data("SELECT id FROM usuarios WHERE username=%s AND rol='SOCIO'", (c_ced,))
                        if user_data:
                            run_query("UPDATE usuarios SET password=%s WHERE id=%s", (c_pwd, user_data[0][0]))
                            registrar_bitacora("RECUPERACION CLAVE", f"El socio CI {c_ced} actualizó su contraseña desde el panel externo.")
                            st.success("✅ ¡Clave actualizada exitosamente! Puede usar el botón 'Volver' para entrar al sistema.")
                        else:
                            st.error("❌ Acción denegada. La cédula no existe o no corresponde a un Socio.")
                    else:
                        st.warning("⚠️ Por favor, llene ambos campos.")

        # PANTALLA NORMAL DE INICIO DE SESIÓN
        else:
            with st.form("login_form"):
                
                if os.path.exists("logo_banco.png"):
                    col_l1, col_l2, col_l3 = st.columns([1, 1.8, 1])
                    with col_l2: st.image("logo_banco.png", use_container_width=True)
                else:
                    st.markdown("<h3 style='text-align: center; color: #091D3E !important; margin-top: 0; margin-bottom: 10px;'>🏦 Banco Familiar</h3>", unsafe_allow_html=True)
                
                user_input = st.text_input("👤 Nombre de Usuario")
                pwd_input = st.text_input("🔒 Contraseña", type="password")
                
                st.checkbox("Recordarme")
                submit_btn = st.form_submit_button("Iniciar Sesión", type="primary")
                
                # El botón de Olvidó Contraseña se renderiza como texto invisible gracias al CSS
                forgot_btn = st.form_submit_button("¿Olvidó su contraseña?", type="secondary")
                
                st.markdown("""
                <div style='text-align: center; line-height: 1.3;'>
                    <p style='font-size: 12px; margin-bottom: 5px; margin-top: 5px;'>¿No tiene cuenta? <span style='color: #1A5632 !important; font-weight: bold;'>Regístrese</span></p>
                    <hr style='border: 0.5px solid #E0DCD0; margin: 10px 0;'>
                    <p style='font-size: 11px; margin-bottom: 0;'>
                        <span style='font-size: 14px;'>📞</span> Servicio al Cliente:<br>
                        <b>1800-GUZMAN</b>
                    </p>
                </div>
                """, unsafe_allow_html=True)
                
                if forgot_btn:
                    st.session_state['show_reset'] = True
                    st.rerun()
                
                if submit_btn:
                    user_clean = clean_text(user_input)
                    pwd_clean = clean_text(pwd_input)
                    usuario_db = fetch_data("SELECT id, rol, socio_id FROM usuarios WHERE username=%s AND password=%s", (user_clean, pwd_clean))
                    if usuario_db:
                        st.session_state.update({'logged_in': True, 'username': user_clean, 'rol': usuario_db[0][1], 'socio_id': usuario_db[0][2]})
                        registrar_bitacora("INICIO DE SESION", f"Acceso exitoso al sistema como {usuario_db[0][1]}")
                        st.rerun()
                    else: 
                        st.error("Credenciales incorrectas.")
                
        st.markdown("""
        <div style='text-align: center; margin-top: 15px; color: #7388A3; font-size: 11px; font-family: sans-serif;'>
            © 2026 Banco de la Familia Guzmán.<br>
            Desarrollado por <b>Patricio Guzmán</b>
        </div>
        """, unsafe_allow_html=True)
        
    st.stop()

# ==========================================
# INTERIOR DEL SISTEMA (DASHBOARD)
# ==========================================
st.markdown("""
<style>
    .stApp { background: #F4F8FB !important; overflow: auto !important; }
    h1, h2, h3 { color: #1F4E78 !important; font-family: 'Helvetica Neue', sans-serif; }
    div[data-testid="metric-container"] { background-color: #FFFFFF; border: 1px solid #E2E8F0; padding: 15px; border-radius: 10px; border-left: 5px solid #1F4E78; }
    div.stButton > button:first-child { background-color: #1F4E78; color: white; border: none; font-weight: 600; }
    div.stButton > button:first-child:hover { background-color: #153654; color: white; }
    [data-testid="stSidebar"] { background-color: #FFFFFF; border-right: 1px solid #E2E8F0; }
    
    /* Logotipo más grande en el menú lateral. Max-width ampliado a 200px */
    [data-testid="stSidebar"] img { max-width: 200px !important; margin: 0 auto !important; display: block; background-color: transparent !important; padding-bottom: 15px; }
    [data-testid="stSidebar"] { overflow: hidden !important; }
    [data-testid="stSidebarNav"] { overflow-y: hidden !important; }
</style>
""", unsafe_allow_html=True)

if os.path.exists("logo_banco.png"): st.sidebar.image("logo_banco.png")
st.sidebar.title("👤 Panel de Control")
st.sidebar.write(f"**USUARIO:** {st.session_state['username']}")
st.sidebar.write(f"**ROL:** {clean_text(st.session_state['rol'])}")
st.sidebar.divider()

hoy_dt = get_guayaquil_time()
hoy_str = format_date(hoy_dt)

def calcular_interes_pendiente(prestamo_id, capital_original, tipo_credito, fecha_otorgamiento_str, fecha_cobro_dt):
    fecha_otorg_dt = parse_date(fecha_otorgamiento_str)
    d_cobro = fecha_cobro_dt.date() if hasattr(fecha_cobro_dt, 'date') else fecha_cobro_dt
    d_otorg = fecha_otorg_dt.date() if hasattr(fecha_otorg_dt, 'date') else fecha_otorg_dt
    dias_transcurridos = (d_cobro - d_otorg).days
    if dias_transcurridos < 0: dias_transcurridos = 0
    meses_calendario = (d_cobro.year - d_otorg.year) * 12 + d_cobro.month - d_otorg.month
    if d_cobro.day < d_otorg.day: meses_calendario -= 1
    meses_calendario = max(0, meses_calendario)
    meses_a_cobrar = 0
    if tipo_credito == "ESPECIAL (0% INTERES)": meses_a_cobrar = 0
    elif tipo_credito == "CORTO PLAZO (5 DIAS)":
        if dias_transcurridos <= 5: meses_a_cobrar = 0
        else: meses_a_cobrar = max(1, meses_calendario)
    else: meses_a_cobrar = max(1, meses_calendario)
    interes_total_generado = capital_original * 0.10 * meses_a_cobrar
    interes_pagado = run_query("SELECT SUM(pago_interes) FROM pagos WHERE prestamo_id = %s", (prestamo_id,), returning=True) or 0.0
    return max(0.0, interes_total_generado - interes_pagado), meses_a_cobrar

if st.session_state['rol'] == 'Administrador':
    menu = st.sidebar.radio("NAVEGACIÓN", ["🏢 INICIO Y DASHBOARD", "👥 SOCIOS", "💵 DEPÓSITOS Y RETIROS", "🤝 CRÉDITOS", "📊 INGRESOS Y EGRESOS", "⚙️ CONFIGURACIÓN", "📖 AUDITORÍA"])
    if st.sidebar.button("CERRAR SESIÓN"):
        registrar_bitacora("CIERRE DE SESION", "El usuario salió del sistema")
        st.session_state.clear(); st.rerun()

    if menu == "🏢 INICIO Y DASHBOARD":
        st.header("RESUMEN FINANCIERO DEL BANCO")
        t_dep = run_query("SELECT SUM(monto) FROM transacciones WHERE tipo = 'DEPOSITO'", returning=True) or 0
        t_ret = run_query("SELECT SUM(monto) FROM transacciones WHERE tipo = 'RETIRO'", returning=True) or 0
        t_ing_ex = run_query("SELECT SUM(monto) FROM flujo_extra WHERE tipo = 'INGRESO'", returning=True) or 0
        t_egr_ex = run_query("SELECT SUM(monto) FROM flujo_extra WHERE tipo = 'EGRESO'", returning=True) or 0
        t_int_gan = run_query("SELECT SUM(pago_interes) FROM pagos", returning=True) or 0
        cap_pres = run_query("SELECT SUM(capital_original) FROM prestamos WHERE estado != 'RECHAZADO'", returning=True) or 0
        cap_dev = run_query("SELECT SUM(pago_capital) FROM pagos", returning=True) or 0
        cap_calle = cap_pres - cap_dev
        saldo_caja = (t_dep - t_ret) + t_ing_ex - t_egr_ex + t_int_gan - cap_calle

        col1, col2, col3 = st.columns(3)
        col1.metric("TOTAL DEPÓSITOS", f"${t_dep:,.2f}")
        col2.metric("TOTAL RETIROS", f"${t_ret:,.2f}")
        col3.metric("CRÉDITOS EN LA CALLE", f"${cap_calle:,.2f}")
        col4, col5, col6 = st.columns(3)
        col4.metric("INGRESOS EXTRAS", f"${t_ing_ex:,.2f}")
        col5.metric("INTERESES GANADOS", f"${t_int_gan:,.2f}")
        col6.metric("TOTAL EGRESOS", f"${t_egr_ex:,.2f}")
        st.divider()
        st.metric("💰 SALDO ACTUAL EN CAJA (EFECTIVO DISPONIBLE)", f"${saldo_caja:,.2f}")
        
        st.write("### 📈 Visualización de Activos")
        if (saldo_caja + cap_calle) > 0 or (t_dep + t_ing_ex + t_int_gan) > 0:
            col_g1, col_g2 = st.columns(2)
            with col_g1:
                fig_pie = px.pie(names=['Caja', 'Préstamos'], values=[max(0, saldo_caja), max(0, cap_calle)], color_discrete_sequence=['#1F4E78', '#38BDF8'], hole=0.4)
                st.plotly_chart(fig_pie, use_container_width=True)
            with col_g2:
                fig_bar = px.bar(x=['Entrada', 'Salida'], y=[t_dep + t_ing_ex + t_int_gan, t_ret + t_egr_ex], color=['Entradas', 'Salidas'], color_discrete_map={'Entradas': '#10B981', 'Salidas': '#EF4444'})
                st.plotly_chart(fig_bar, use_container_width=True)

        st.write("---")
        def crear_pdf_resumen():
            pdf = BancoPDF()
            pdf.add_page()
            pdf.set_font("Arial", 'B', 14); pdf.set_text_color(80, 80, 80)
            pdf.cell(0, 10, clean_text("Resumen Financiero Consolidado"), ln=True, align='C')
            pdf.set_font("Arial", '', 10); pdf.cell(0, 5, f"FECHA DE CORTE: {hoy_str}", ln=True, align='C'); pdf.ln(10)
            def add_row(label, value, fill_row):
                if fill_row: pdf.set_fill_color(244, 248, 251)
                else: pdf.set_fill_color(255, 255, 255)
                pdf.set_text_color(51, 51, 51); pdf.set_font("Arial", 'B', 11)
                pdf.cell(100, 10, label, border=1, fill=True); pdf.set_font("Arial", '', 11)
                pdf.cell(50, 10, value, border=1, fill=True, ln=True, align='R')
            pdf.set_draw_color(226, 232, 240)
            add_row("TOTAL DEPOSITOS:", f"${t_dep:,.2f}", False)
            add_row("TOTAL RETIROS:", f"${t_ret:,.2f}", True)
            add_row("INGRESOS EXTRAS:", f"${t_ing_ex:,.2f}", False)
            add_row("INTERESES GANADOS:", f"${t_int_gan:,.2f}", True)
            add_row("TOTAL EGRESOS (GASTOS):", f"${t_egr_ex:,.2f}", False)
            add_row("CREDITOS VIGENTES (EN CALLE):", f"${cap_calle:,.2f}", True)
            pdf.ln(5)
            pdf.set_fill_color(31, 78, 120); pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", 'B', 14)
            pdf.cell(100, 12, "SALDO ACTUAL EN CAJA:", border=0, fill=True)
            pdf.cell(50, 12, f"${saldo_caja:,.2f}", border=0, fill=True, ln=True, align='R')
            try: return pdf.output(dest='S').encode('latin1')
            except: return bytes(pdf.output())

        st.download_button("📄 EXPORTAR RESUMEN OFICIAL A PDF", data=crear_pdf_resumen(), file_name="RESUMEN_FINANCIERO.pdf", mime="application/pdf")

    elif menu == "👥 SOCIOS":
        st.header("GESTIÓN DE SOCIOS")
        tab1, tab2, tab3 = st.tabs(["LISTADO Y EXPORTACIÓN", "NUEVO SOCIO", "EDITAR / ELIMINAR"])
        with tab1:
            query_reporte = '''SELECT s.cedula as "CEDULA", s.nombres as "NOMBRES", s.apellidos as "APELLIDOS", COALESCE((SELECT SUM(monto) FROM transacciones WHERE socio_id = s.id AND tipo = 'DEPOSITO'), 0) - COALESCE((SELECT SUM(monto) FROM transacciones WHERE socio_id = s.id AND tipo = 'RETIRO'), 0) AS "SALDO CUENTA", CASE WHEN (SELECT COUNT(*) FROM prestamos WHERE socio_id = s.id AND estado = 'VIGENTE') > 0 THEN 'SI' ELSE 'NO' END AS "TIENE CREDITO" FROM socios s'''
            df_reporte = get_dataframe(query_reporte)
            st.dataframe(df_reporte, use_container_width=True)
            col_pdf, col_excel = st.columns(2)
            with col_excel:
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer: df_reporte.to_excel(writer, index=False, sheet_name='SOCIOS')
                st.download_button("📊 EXPORTAR BASE EN EXCEL", data=output.getvalue(), file_name="REPORTE_SOCIOS.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            with col_pdf:
                def crear_pdf_socios():
                    pdf = BancoPDF()
                    pdf.add_page()
                    pdf.set_font("Arial", 'B', 14); pdf.set_text_color(80, 80, 80)
                    pdf.cell(0, 10, clean_text("Reporte Oficial de Socios"), ln=True, align='C')
                    pdf.set_font("Arial", '', 10); pdf.cell(0, 5, f"FECHA: {hoy_str}", ln=True, align='C'); pdf.ln(5)
                    pdf.set_fill_color(31, 78, 120); pdf.set_text_color(255, 255, 255); pdf.set_draw_color(31, 78, 120); pdf.set_font("Arial", 'B', 10)
                    anchos = [30, 45, 45, 35, 30]
                    cabeceras = ["CEDULA", "NOMBRES", "APELLIDOS", "SALDO", "CREDITO"]
                    for i, h in enumerate(cabeceras): pdf.cell(anchos[i], 10, h, border=1, fill=True, align='C')
                    pdf.ln()
                    pdf.set_draw_color(226, 232, 240)
                    fill = False
                    for index, row in df_reporte.iterrows():
                        if fill: pdf.set_fill_color(244, 248, 251)
                        else: pdf.set_fill_color(255, 255, 255)
                        pdf.set_text_color(51, 51, 51); pdf.set_font("Arial", '', 9)
                        pdf.cell(anchos[0], 10, str(row['CEDULA']), border=1, fill=True, align='C')
                        pdf.cell(anchos[1], 10, str(row['NOMBRES'])[:20], border=1, fill=True)
                        pdf.cell(anchos[2], 10, str(row['APELLIDOS'])[:20], border=1, fill=True)
                        pdf.set_font("Arial", 'B', 9); pdf.set_text_color(31, 78, 120)
                        pdf.cell(anchos[3], 10, f"${row['SALDO CUENTA']:.2f}", border=1, fill=True, align='R')
                        pdf.set_text_color(51, 51, 51); pdf.set_font("Arial", '', 9)
                        pdf.cell(anchos[4], 10, str(row['TIENE CREDITO']), border=1, fill=True, align='C')
                        pdf.ln()
                        fill = not fill
                    try: return pdf.output(dest='S').encode('latin1')
                    except: return bytes(pdf.output())
                st.download_button("📄 GENERAR REPORTE EN PDF", data=crear_pdf_socios(), file_name="REPORTE_SOCIOS.pdf", mime="application/pdf")

        with tab2:
            with st.form("form_nuevo_socio", clear_on_submit=True):
                col_form1, col_form2 = st.columns(2)
                with col_form1: ced = st.text_input("NÚMERO DE CÉDULA"); nom = st.text_input("NOMBRES"); ape = st.text_input("APELLIDOS")
                with col_form2: tel = st.text_input("TELÉFONO"); correo = st.text_input("CORREO ELECTRÓNICO"); st.write("<br><br>", unsafe_allow_html=True); submit_socio = st.form_submit_button("REGISTRAR SOCIO")
                if submit_socio:
                    c_ced = clean_text(ced)
                    if c_ced:
                        try:
                            nuevo_id = run_query("INSERT INTO socios (cedula, nombres, apellidos, telefono, correo, fecha_registro) VALUES (%s,%s,%s,%s,%s,%s)", (c_ced, clean_text(nom), clean_text(ape), clean_text(tel), clean_text(correo), hoy_str))
                            run_query("INSERT INTO usuarios (username, password, rol, socio_id) VALUES (%s, %s, 'SOCIO', %s)", (c_ced, c_ced, nuevo_id))
                            registrar_bitacora("NUEVO SOCIO", f"Registrado Socio: {clean_text(nom)} {clean_text(ape)} (CI: {c_ced})")
                            st.success("SOCIO REGISTRADO CON ÉXITO.")
                        except Exception: st.error("LA CÉDULA YA ESTÁ REGISTRADA O HUBO UN ERROR.")
                    else: st.error("LA CÉDULA ES OBLIGATORIA.")

        with tab3:
            lista_socios = get_dataframe("SELECT id, cedula, nombres, apellidos FROM socios")
            if not lista_socios.empty:
                socio_sel = st.selectbox("SELECCIONE UN SOCIO", lista_socios['id'].astype(str) + " - " + lista_socios['nombres'] + " " + lista_socios['apellidos'])
                id_sel = socio_sel.split(" - ")[0]; nom_sel = socio_sel.split(" - ")[1]
                datos_actuales = fetch_data("SELECT cedula, nombres, apellidos, telefono, correo FROM socios WHERE id=%s", (id_sel,))[0]
                with st.form("form_editar_socio"):
                    col_ed1, col_ed2 = st.columns(2)
                    with col_ed1: e_ced = st.text_input("CÉDULA", value=datos_actuales[0]); e_nom = st.text_input("NOMBRES", value=datos_actuales[1]); e_ape = st.text_input("APELLIDOS", value=datos_actuales[2])
                    with col_ed2: e_tel = st.text_input("TELÉFONO", value=datos_actuales[3]); e_correo = st.text_input("CORREO", value=datos_actuales[4]); st.write("<br><br>", unsafe_allow_html=True); btn_editar = st.form_submit_button("GUARDAR CAMBIOS")
                    if btn_editar:
                        run_query("UPDATE socios SET cedula=%s, nombres=%s, apellidos=%s, telefono=%s, correo=%s WHERE id=%s", (clean_text(e_ced), clean_text(e_nom), clean_text(e_ape), clean_text(e_tel), clean_text(e_correo), id_sel))
                        registrar_bitacora("EDITAR SOCIO", f"Actualizados datos del Socio ID: {id_sel}")
                        st.success("DATOS ACTUALIZADOS."); st.rerun()
                st.divider()
                if st.button("ELIMINAR SOCIO DEFINITIVAMENTE", type="primary"):
                    run_query("DELETE FROM usuarios WHERE socio_id = %s", (id_sel,)); run_query("DELETE FROM socios WHERE id = %s", (id_sel,))
                    registrar_bitacora("ELIMINAR SOCIO", f"Socio eliminado: {nom_sel} (ID: {id_sel})")
                    st.success("SOCIO ELIMINADO."); st.rerun()

    elif menu == "💵 DEPÓSITOS Y RETIROS":
        st.header("CAJAS - DEPÓSITOS Y RETIROS")
        socios = get_dataframe("SELECT id, nombres, apellidos FROM socios")
        if not socios.empty:
            with st.form("form_trx"):
                col_tx1, col_tx2 = st.columns(2)
                with col_tx1: socio_id = st.selectbox("SELECCIONAR SOCIO", socios['id'].astype(str) + " - " + socios['nombres'] + " " + socios['apellidos']); tipo = st.radio("TIPO DE TRANSACCIÓN", ["DEPOSITO", "RETIRO"], horizontal=True)
                with col_tx2: monto = st.number_input("MONTO DE LA TRANSACCIÓN ($)", min_value=0.01, step=10.0); st.write(""); submit_tx = st.form_submit_button("PROCESAR TRANSACCIÓN")
                if submit_tx:
                    s_id = socio_id.split(" - ")[0]; nombre_socio = socio_id.split(" - ")[1]
                    tx_id = run_query("INSERT INTO transacciones (socio_id, tipo, monto, fecha) VALUES (%s,%s,%s,%s)", (s_id, clean_text(tipo), monto, hoy_str))
                    registrar_bitacora("TRANSACCION CAJA", f"{clean_text(tipo)} por ${monto:.2f} a cuenta del socio {nombre_socio}")
                    pdf_bytes = generar_comprobante("COMPROBANTE DE TRANSACCION", f"TX-{tx_id}", nombre_socio, {"TIPO DE MOVIMIENTO": clean_text(tipo), "MONTO PROCESADO": f"${monto:,.2f}", "ESTADO": "COMPLETADO"})
                    st.session_state['ultimo_recibo_tx'] = pdf_bytes; st.session_state['nombre_recibo_tx'] = f"Comprobante_{clean_text(tipo)}_{s_id}.pdf"
                    st.success(f"EL {clean_text(tipo)} POR ${monto:,.2f} HA SIDO REGISTRADO EXITOSAMENTE.")
            if 'ultimo_recibo_tx' in st.session_state: st.download_button("📥 DESCARGAR COMPROBANTE EN PDF", data=st.session_state['ultimo_recibo_tx'], file_name=st.session_state['nombre_recibo_tx'], mime="application/pdf")

    elif menu == "🤝 CRÉDITOS":
        st.header("GESTIÓN DE CRÉDITOS Y COBRANZAS")
        tab_solicitudes, tab_otorgar, tab_cobrar, tab_reporte = st.tabs(["REVISAR SOLICITUDES", "OTORGAR CRÉDITO DIRECTO", "COBRAR CUOTAS", "REPORTE DE VIGENTES"])
        
        with tab_solicitudes:
            solicitudes = get_dataframe('SELECT p.id, s.nombres, s.apellidos, p.capital_original as "CAPITAL_ORIGINAL", p.tipo_credito as "TIPO_CREDITO" FROM prestamos p JOIN socios s ON p.socio_id = s.id WHERE p.estado = \'SOLICITADO\'')
            if not solicitudes.empty:
                for _, row in solicitudes.iterrows():
                    st.info(f"**SOLICITUD PENDIENTE:** {row['nombres']} {row['apellidos']} solicita **${row['CAPITAL_ORIGINAL']}** bajo la modalidad **{row['TIPO_CREDITO']}**.")
                    col1, col2, col3 = st.columns([2, 1, 1])
                    with col1: f_otorga = st.date_input(f"FECHA DE OTORGAMIENTO (ID:{row['id']})", value=hoy_dt.date())
                    with col2: 
                        st.write("<br>", unsafe_allow_html=True)
                        if st.button("✅ APROBAR", key=f"apr_{row['id']}", use_container_width=True):
                            run_query("UPDATE prestamos SET estado='VIGENTE', fecha_otorgamiento=%s WHERE id=%s", (format_date(f_otorga), row['id']))
                            registrar_bitacora("CREDITO APROBADO", f"Crédito ID {row['id']} por ${row['CAPITAL_ORIGINAL']} a {row['nombres']} {row['apellidos']}")
                            st.rerun()
                    with col3:
                        st.write("<br>", unsafe_allow_html=True)
                        if st.button("❌ RECHAZAR", key=f"rec_{row['id']}", use_container_width=True):
                            run_query("UPDATE prestamos SET estado='RECHAZADO' WHERE id=%s", (row['id'],)); st.rerun()
                    st.write("---")
            else: st.info("No hay solicitudes pendientes en la bandeja de entrada.")

        with tab_otorgar:
            socios = get_dataframe("SELECT id, nombres, apellidos FROM socios")
            if not socios.empty:
                with st.form("form_credito_directo"):
                    col_cr1, col_cr2 = st.columns(2)
                    with col_cr1: socio_cred = st.selectbox("SOCIO BENEFICIARIO", socios['id'].astype(str) + " - " + socios['nombres'] + " " + socios['apellidos']); capital = st.number_input("CAPITAL A PRESTAR ($)", min_value=1.0, step=100.0)
                    with col_cr2: tipo_cred = st.selectbox("TIPO DE CONDICIÓN", ["NORMAL (10% MENSUAL)", "CORTO PLAZO (5 DIAS)", "ESPECIAL (0% INTERES)"]); fecha_ot = st.date_input("FECHA DE OTORGAMIENTO", value=hoy_dt.date())
                    st.write(""); 
                    if st.form_submit_button("EMITIR CRÉDITO Y PASAR A VIGENTE"):
                        s_id = socio_cred.split(" - ")[0]; nombre_socio = socio_cred.split(" - ")[1]
                        run_query("INSERT INTO prestamos (socio_id, capital_original, saldo_capital, tipo_credito, estado, fecha_solicitud, fecha_otorgamiento) VALUES (%s,%s,%s,%s,%s,%s,%s)", (s_id, capital, capital, clean_text(tipo_cred), 'VIGENTE', hoy_str, format_date(fecha_ot)))
                        registrar_bitacora("CREDITO DIRECTO OTORGADO", f"Se otorgó ${capital} a {nombre_socio} bajo {tipo_cred}"); st.success("CRÉDITO GENERADO E INGRESADO A LA CARTERA VIGENTE.")
        
        with tab_cobrar:
            prestamos_vig = get_dataframe('SELECT p.id, s.nombres, s.apellidos, p.saldo_capital as "SALDO_CAPITAL", p.capital_original as "CAPITAL_ORIGINAL", p.fecha_otorgamiento as "FECHA_OTORGAMIENTO", p.tipo_credito as "TIPO_CREDITO" FROM prestamos p JOIN socios s ON p.socio_id = s.id WHERE p.estado = \'VIGENTE\'')
            if not prestamos_vig.empty:
                opciones = prestamos_vig['id'].astype(str) + " - " + prestamos_vig['nombres'] + " " + prestamos_vig['apellidos'] + " - Capital Original: $" + prestamos_vig['CAPITAL_ORIGINAL'].astype(str)
                p_sel_str = st.selectbox("BUSCAR PRÉSTAMO ACTIVO", opciones)
                
                p_id = int(p_sel_str.split(" - ")[0])
                nombre_socio = p_sel_str.split(" - ")[1]
                p_data = prestamos_vig[prestamos_vig['id'] == p_id].iloc[0]
                
                col_f1, col_f2 = st.columns([1, 2])
                with col_f1: fecha_cobro = st.date_input("FECHA DE COBRO A APLICAR", value=hoy_dt.date())
                interes_pendiente, meses_transcurridos = calcular_interes_pendiente(p_id, p_data['CAPITAL_ORIGINAL'], p_data['TIPO_CREDITO'], p_data['FECHA_OTORGAMIENTO'], fecha_cobro)
                with col_f2: st.info(f"📅 **FECHA DE OTORGAMIENTO:** {p_data['FECHA_OTORGAMIENTO']} &nbsp;&nbsp;|&nbsp;&nbsp; ⏳ **MESES TRANSCURRIDOS:** {meses_transcurridos} mes(es)")
                
                st.warning(f"💰 **SALDO CAPITAL ACTUAL:** ${p_data['SALDO_CAPITAL']:,.2f} &nbsp;&nbsp;|&nbsp;&nbsp; 📈 **INTERÉS GENERADO A LA FECHA:** ${interes_pendiente:,.2f}")
                
                st.write("### DETALLE DE PAGO")
                col_p1, col_p2 = st.columns(2)
                with col_p1: 
                    pago_cap = st.number_input("ABONO AL CAPITAL ($)", min_value=0.0, max_value=float(p_data['SALDO_CAPITAL']), step=10.0, value=float(p_data['SALDO_CAPITAL']))
                with col_p2: 
                    pago_int = st.number_input("PAGO DE INTERÉS ($)", min_value=0.0, step=5.0, value=float(interes_pendiente))
                
                total_a_pagar = pago_cap + pago_int
                st.markdown(f"<div style='background-color: #E2E8F0; padding: 15px; border-radius: 8px; text-align: center; margin-top: 10px; margin-bottom: 20px;'><h2 style='color: #1F4E78; margin: 0;'>TOTAL A PAGAR: ${total_a_pagar:,.2f}</h2></div>", unsafe_allow_html=True)
                
                if st.button("CONFIRMAR RECEPCIÓN DE PAGO", type="primary", use_container_width=True):
                    run_query("UPDATE prestamos SET saldo_capital = saldo_capital - %s WHERE id = %s", (pago_cap, p_id))
                    pago_id = run_query("INSERT INTO pagos (prestamo_id, pago_capital, pago_interes, fecha) VALUES (%s,%s,%s,%s)", (p_id, pago_cap, pago_int, format_date(fecha_cobro)))
                    registrar_bitacora("PAGO DE CREDITO", f"Cobro a {nombre_socio}: Capital ${pago_cap} / Interés ${pago_int}")
                    nuevo_saldo = run_query("SELECT saldo_capital FROM prestamos WHERE id = %s", (p_id,), returning=True)
                    if nuevo_saldo <= 0: run_query("UPDATE prestamos SET estado = 'PAGADO' WHERE id = %s", (p_id,)); st.success("¡EL CRÉDITO HA SIDO LIQUIDADO EN SU TOTALIDAD!")
                    else: st.success("PAGO APLICADO CORRECTAMENTE.")
                    pdf_bytes = generar_comprobante("RECIBO DE PAGO", f"PG-{pago_id}", nombre_socio, {"CONCEPTO": "PAGO DE CUOTA DE CREDITO", "ABONO A CAPITAL": f"${pago_cap:,.2f}", "PAGO DE INTERESES": f"${pago_int:,.2f}", "TOTAL CANCELADO": f"${(pago_cap + pago_int):,.2f}", "SALDO PENDIENTE (CAPITAL)": f"${nuevo_saldo:,.2f}"})
                    st.session_state['ultimo_recibo_pago'] = pdf_bytes; st.session_state['nombre_recibo_pago'] = f"Recibo_Pago_{p_id}.pdf"
            
            if 'ultimo_recibo_pago' in st.session_state: 
                st.download_button("📥 DESCARGAR COMPROBANTE DE PAGO EN PDF", data=st.session_state['ultimo_recibo_pago'], file_name=st.session_state['nombre_recibo_pago'], mime="application/pdf")
        
        with tab_reporte:
            st.write("### REPORTE OFICIAL DE CRÉDITOS VIGENTES")
            df_activos = get_dataframe('SELECT p.id, s.nombres, s.apellidos, p.saldo_capital as "SALDO_CAPITAL", p.capital_original as "CAPITAL_ORIGINAL", p.fecha_otorgamiento as "FECHA_OTORGAMIENTO", p.tipo_credito as "TIPO_CREDITO" FROM prestamos p JOIN socios s ON p.socio_id = s.id WHERE p.estado = \'VIGENTE\'')
            
            if not df_activos.empty:
                reporte_data = []
                total_cap = 0.0
                total_int = 0.0
                
                for _, row in df_activos.iterrows():
                    int_pend, meses = calcular_interes_pendiente(row['id'], row['CAPITAL_ORIGINAL'], row['TIPO_CREDITO'], row['FECHA_OTORGAMIENTO'], hoy_dt)
                    total_cap += row['SALDO_CAPITAL']
                    total_int += int_pend
                    reporte_data.append({
                        "SOCIO": f"{row['nombres']} {row['apellidos']}",
                        "FECHA OTORG.": row['FECHA_OTORGAMIENTO'],
                        "MESES": meses,
                        "CAPITAL VIGENTE": row['SALDO_CAPITAL'],
                        "INTERÉS GENERADO": round(int_pend, 2),
                        "TOTAL ESPERADO": round(row['SALDO_CAPITAL'] + int_pend, 2)
                    })
                
                df_rep = pd.DataFrame(reporte_data)
                st.dataframe(df_rep, use_container_width=True)
                
                col_t1, col_t2, col_t3 = st.columns(3)
                col_t1.metric("TOTAL CAPITAL EN LA CALLE", f"${total_cap:,.2f}")
                col_t2.metric("TOTAL INTERESES POR COBRAR", f"${total_int:,.2f}")
                col_t3.metric("GRAN TOTAL ESPERADO", f"${(total_cap + total_int):,.2f}")
                
                def crear_pdf_reporte_creditos():
                    pdf = BancoPDF()
                    pdf.add_page()
                    pdf.set_font("Arial", 'B', 14)
                    pdf.set_text_color(80, 80, 80)
                    pdf.cell(0, 10, clean_text("Reporte de Creditos Activos (En la Calle)"), ln=True, align='C')
                    pdf.set_font("Arial", '', 10)
                    pdf.cell(0, 5, f"FECHA DE CORTE: {hoy_str}", ln=True, align='C')
                    pdf.ln(5)
                    
                    pdf.set_fill_color(31, 78, 120)
                    pdf.set_text_color(255, 255, 255)
                    pdf.set_draw_color(31, 78, 120)
                    pdf.set_font("Arial", 'B', 9)
                    anchos = [55, 25, 20, 30, 30, 30]
                    cabs = ["SOCIO", "FECHA", "MESES", "CAPITAL", "INTERES", "TOTAL"]
                    for i, h in enumerate(cabs):
                        pdf.cell(anchos[i], 10, h, border=1, fill=True, align='C')
                    pdf.ln()
                    
                    pdf.set_draw_color(226, 232, 240)
                    fill = False
                    for d in reporte_data:
                        if fill: pdf.set_fill_color(244, 248, 251)
                        else: pdf.set_fill_color(255, 255, 255)
                        pdf.set_text_color(51, 51, 51)
                        pdf.set_font("Arial", '', 8)
                        pdf.cell(anchos[0], 10, str(d['SOCIO'])[:28], border=1, fill=True)
                        pdf.cell(anchos[1], 10, str(d['FECHA OTORG.']), border=1, fill=True, align='C')
                        pdf.cell(anchos[2], 10, str(d['MESES']), border=1, fill=True, align='C')
                        pdf.cell(anchos[3], 10, f"${d['CAPITAL VIGENTE']:,.2f}", border=1, fill=True, align='R')
                        pdf.cell(anchos[4], 10, f"${d['INTERÉS GENERADO']:,.2f}", border=1, fill=True, align='R')
                        pdf.set_font("Arial", 'B', 8)
                        pdf.cell(anchos[5], 10, f"${d['TOTAL ESPERADO']:,.2f}", border=1, fill=True, align='R')
                        pdf.ln()
                        fill = not fill
                    
                    pdf.ln(5)
                    pdf.set_fill_color(31, 78, 120)
                    pdf.set_text_color(255, 255, 255)
                    pdf.set_font("Arial", 'B', 10)
                    pdf.cell(100, 10, "TOTALES GENERALES:", border=0, fill=True, align='R')
                    pdf.cell(30, 10, f"${total_cap:,.2f}", border=0, fill=True, align='R')
                    pdf.cell(30, 10, f"${total_int:,.2f}", border=0, fill=True, align='R')
                    pdf.cell(30, 10, f"${(total_cap+total_int):,.2f}", border=0, fill=True, align='R')
                    
                    try: return pdf.output(dest='S').encode('latin1')
                    except: return bytes(pdf.output())
                    
                st.download_button("📄 EXPORTAR REPORTE EN PDF", data=crear_pdf_reporte_creditos(), file_name="REPORTE_CREDITOS_VIGENTES.pdf", mime="application/pdf")
            else:
                st.info("No hay créditos vigentes en este momento.")

    elif menu == "📊 INGRESOS Y EGRESOS":
        st.header("GESTIÓN DE CAJA CHICA Y EXTRAORDINARIOS")
        with st.form("form_flujo"):
            col_fl1, col_fl2 = st.columns(2)
            with col_fl1: tipo_flujo = st.selectbox("DIRECCIÓN DEL FLUJO", ["INGRESO", "EGRESO"]); monto_flujo = st.number_input("MONTO IMPLICADO ($)", min_value=0.01, step=10.0)
            with col_fl2: categoria = st.selectbox("CLASIFICACIÓN", ["DONACION", "GASTO ADMINISTRATIVO", "MANTENIMIENTO", "OTRO"]); desc = st.text_input("CONCEPTO / DESCRIPCIÓN")
            st.write(""); 
            if st.form_submit_button("REGISTRAR ASIENTO CONTABLE"):
                run_query("INSERT INTO flujo_extra (tipo, categoria, monto, descripcion, fecha) VALUES (%s,%s,%s,%s,%s)", (clean_text(tipo_flujo), clean_text(categoria), monto_flujo, clean_text(desc), hoy_str))
                registrar_bitacora("FLUJO EXTRA", f"{tipo_flujo} por ${monto_flujo}: {clean_text(desc)}"); st.success("REGISTRO GUARDADO EN EL LIBRO MAYOR.")

    elif menu == "⚙️ CONFIGURACIÓN":
        st.header("PANEL DE SEGURIDAD Y CONFIGURACIÓN VISUAL")
        tab_lista, tab_nuevo, tab_config = st.tabs(["CREDENCIALES ACTIVAS", "NUEVO ADMINISTRADOR", "IDENTIDAD VISUAL"])
        with tab_lista:
            df_usuarios = get_dataframe('SELECT id as "ID", username as "USUARIO", rol as "ROL" FROM usuarios')
            st.dataframe(df_usuarios, use_container_width=True)
            st.write("---"); st.write("### FORZAR RESTABLECIMIENTO DE CONTRASEÑA")
            with st.form("reset_pwd"):
                col_rp1, col_rp2 = st.columns(2)
                with col_rp1: usr_sel = st.selectbox("USUARIO OBJETIVO", df_usuarios['USUARIO'])
                with col_rp2: new_pwd = st.text_input("NUEVA CLAVE DE ACCESO", type="password"); st.write(""); btn = st.form_submit_button("EJECUTAR CAMBIO DE CLAVE")
                if btn:
                    run_query("UPDATE usuarios SET password=%s WHERE username=%s", (clean_text(new_pwd), usr_sel)); registrar_bitacora("SEGURIDAD", f"Se forzó el cambio de contraseña para el usuario {usr_sel}"); st.success("LA CONTRASEÑA HA SIDO ACTUALIZADA EN EL SISTEMA.")
        with tab_nuevo:
            with st.form("new_admin"):
                col_na1, col_na2 = st.columns(2)
                with col_na1: a_usr = st.text_input("NUEVO ALIAS (USUARIO)")
                with col_na2: a_pwd = st.text_input("CONTRASEÑA INICIAL", type="password")
                st.write(""); 
                if st.form_submit_button("CONCEDER PERMISOS DE ADMINISTRADOR"):
                    try: run_query("INSERT INTO usuarios (username, password, rol) VALUES (%s, %s, 'ADMINISTRADOR')", (clean_text(a_usr), clean_text(a_pwd))); registrar_bitacora("SEGURIDAD", f"Creado nuevo usuario Administrador: {clean_text(a_usr)}"); st.success("ADMINISTRADOR CREADO Y ACTIVO.")
                    except: st.error("EL ALIAS INDICADO YA SE ENCUENTRA EN USO.")
        
        with tab_config:
            st.write("### CONFIGURAR LOGOTIPO DEL BANCO")
            st.info("💡 **Despliegue en la Nube:** Para que la imagen del logotipo sea permanente en internet, debes añadir el archivo `logo_banco.png` directamente a tu repositorio en GitHub.")
            if os.path.exists("logo_banco.png"):
                st.image("logo_banco.png", width=150)
            else:
                st.warning("No se encontró el archivo 'logo_banco.png' en la carpeta actual del proyecto.")
                        
        st.write("<br><br>", unsafe_allow_html=True); st.error("### ⚠️ ZONA DE PELIGRO: FORMATEO DEL SISTEMA")
        with st.expander("DESPLEGAR OPCIONES DE REINICIO TOTAL"):
            confirm_text = st.text_input("Transcriba exactamente: 'BORRAR TODO'")
            if st.button("🔥 PURGAR BASE DE DATOS Y REINICIAR", type="primary"):
                if confirm_text == 'BORRAR TODO':
                    for table in ["pagos", "prestamos", "transacciones", "flujo_extra", "usuarios", "socios", "bitacora"]:
                        run_query(f"DELETE FROM {table} CASCADE")
                    run_query("INSERT INTO usuarios (username, password, rol) VALUES ('ADMIN', 'ADMIN', 'Administrador')")
                    st.success("PURGA COMPLETADA. EL SISTEMA SE REINICIARÁ AHORA."); st.session_state.clear(); st.rerun()
                else: st.error("La frase de seguridad no coincide. Operación abortada.")

    elif menu == "📖 AUDITORÍA":
        st.header("LIBRO DE AUDITORÍA DEL SISTEMA")
        df_bitacora = get_dataframe('SELECT id as "ID", fecha as "FECHA_HORA", usuario as "RESPONSABLE", accion as "EVENTO", detalle as "DESCRIPCION" FROM bitacora ORDER BY id DESC')
        st.dataframe(df_bitacora, use_container_width=True)

elif st.session_state['rol'] == 'SOCIO':
    menu = st.sidebar.radio("MI PORTAL", ["📊 MI ESTADO DE CUENTA", "🤝 MIS PRÉSTAMOS"])
    mi_id = st.session_state['socio_id']
    if st.sidebar.button("CERRAR SESIÓN"): st.session_state.clear(); st.rerun()
    
    if menu == "📊 MI ESTADO DE CUENTA":
        st.header("MIS AHORROS Y MOVIMIENTOS")
        dep = run_query("SELECT SUM(monto) FROM transacciones WHERE socio_id=%s AND tipo='DEPOSITO'", (mi_id,), returning=True) or 0
        ret = run_query("SELECT SUM(monto) FROM transacciones WHERE socio_id=%s AND tipo='RETIRO'", (mi_id,), returning=True) or 0
        st.metric("LIQUIDEZ DISPONIBLE (SALDO)", f"${(dep - ret):,.2f}")
        st.dataframe(get_dataframe('SELECT fecha as "FECHA", tipo as "TIPO", monto as "MONTO" FROM transacciones WHERE socio_id=%s ORDER BY id DESC', (mi_id,)), use_container_width=True)
        
    elif menu == "🤝 MIS PRÉSTAMOS":
        st.header("MI CARTERA DE CRÉDITOS")
        tab_lista, tab_solicitar = st.tabs(["HISTORIAL", "NUEVA SOLICITUD"])
        with tab_lista:
            df_mis_prestamos = get_dataframe('SELECT capital_original as "CAPITAL", saldo_capital as "PENDIENTE", tipo_credito as "TIPO", estado as "ESTADO", fecha_solicitud as "SOLICITADO", fecha_otorgamiento as "OTORGADO" FROM prestamos WHERE socio_id=%s', (mi_id,))
            if not df_mis_prestamos.empty: st.dataframe(df_mis_prestamos, use_container_width=True)
            else: st.info("Su historial de créditos está vacío.")
                
        with tab_solicitar:
            with st.form("form_solicitar"):
                monto_solicitado = st.number_input("MONTO REQUERIDO ($)", min_value=10.0, step=10.0)
                tipo_cred = st.selectbox("MODALIDAD DE CRÉDITO", ["NORMAL (10% MENSUAL)", "CORTO PLAZO (5 DIAS)", "ESPECIAL (0% INTERES)"])
                st.write(""); 
                if st.form_submit_button("RADICAR SOLICITUD DE CRÉDITO"):
                    run_query("INSERT INTO prestamos (socio_id, capital_original, saldo_capital, tipo_credito, estado, fecha_solicitud) VALUES (%s,%s,%s,%s,%s,%s)", (mi_id, monto_solicitado, monto_solicitado, clean_text(tipo_cred), 'SOLICITADO', hoy_str))
                    registrar_bitacora("NUEVA SOLICITUD", f"El socio ID {mi_id} solicitó crédito de ${monto_solicitado}")
                    st.success("LA SOLICITUD HA INGRESADO EXITOSAMENTE A LA BANDEJA DE APROBACIONES.")
