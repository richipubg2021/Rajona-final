import os
import random
import sqlite3
import time
from threading import Thread
from flask import Flask
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --- MINI SERVIDOR WEB PARA QUE RENDER ACEPTE EL PLAN GRATUITO ---
app_flask = Flask('')

@app_flask.route('/')
def home():
    return "¡El bot está vivo y funcionando!"

def run_flask():
    app_flask.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- CONFIGURACIÓN ---
TOKEN = "9230845768:AAGyLDa9vUuC4nAC6nNfR1IUeV7JzTISChw"
ADMIN_ID = 8584917327
ADMIN_USERNAME = "Demboy_chile"

# Diccionario temporal para el control de spam (Cooldown de 3 segundos)
user_cooldowns = {}

# --- BASE DE DATOS Y MODO WAL ---
def init_db():
    conn = sqlite3.connect("bot_rajona.db")
    cursor = conn.cursor()
    
    # Activar el modo WAL para evitar bloqueos de concurrencia
    cursor.execute("PRAGMA journal_mode=WAL;")
    
    # Tabla de imágenes
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT NOT NULL,
            weight INTEGER DEFAULT 1,
            caption TEXT DEFAULT ''
        )
    """
    )
    # Tabla de configuraciones del bot
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """
    )
    # Tabla de usuarios bloqueados
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY
        )
    """
    )
    # Tabla para registrar usuarios recientes y facilitar su bloqueo
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS recent_users (
            user_id INTEGER PRIMARY KEY,
            display_name TEXT
        )
    """
    )
    conn.commit()
    conn.close()

init_db()

def get_setting(key, default_val):
    conn = sqlite3.connect("bot_rajona.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default_val

def set_setting(key, val):
    conn = sqlite3.connect("bot_rajona.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, val))
    conn.commit()
    conn.close()

def is_banned(user_id):
    conn = sqlite3.connect("bot_rajona.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM banned_users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def register_user(user):
    user_id = user.id
    name = user.username and f"@{user.username}" or user.first_name or f"Usuario {user_id}"
    conn = sqlite3.connect("bot_rajona.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO recent_users (user_id, display_name) VALUES (?, ?)", (user_id, name))
    conn.commit()
    conn.close()

# --- COMANDO /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id) and user.id != ADMIN_ID:
        return

    register_user(user)
    chat_type = update.effective_chat.type

    welcome_msg = get_setting("welcome_message", "¡Hola! Presiona el botón para recibir tu foto al azar:")
    btn_text = get_setting("button_text", "🎲 Rajona al azar")
    contact_btn_text = get_setting("contact_btn_text", "💬 Hablar con el Admin")
    contact_link = get_setting("contact_link", f"https://t.me/{ADMIN_USERNAME}")

    keyboard_buttons = [
        [InlineKeyboardButton(btn_text, callback_data="rajona_azur")],
        [InlineKeyboardButton(contact_btn_text, url=contact_link)]
    ]

    if chat_type != "private":
        keyboard_buttons.insert(0, [InlineKeyboardButton(btn_text, callback_data="rajona_azur")])
        await update.message.reply_text(
            "¡Hola! Presiona el botón de abajo para recibir tu contenido por mensaje privado:",
            reply_markup=InlineKeyboardMarkup(keyboard_buttons)
        )
        return

    if user.id == ADMIN_ID:
        keyboard_buttons.append([InlineKeyboardButton("⚙️ Panel de Administración", callback_data="admin_menu")])
        await update.message.reply_text(
            "¡Hola Admin! Elige una opción:",
            reply_markup=InlineKeyboardMarkup(keyboard_buttons)
        )
    else:
        await update.message.reply_text(
            welcome_msg,
            reply_markup=InlineKeyboardMarkup(keyboard_buttons)
        )

# --- PANEL DE ADMINISTRACIÓN (Limpia el menú anterior y pone uno nuevo abajo) ---
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📋 Ver / Editar / Borrar Fotos", callback_data="list_images")],
        [InlineKeyboardButton("🚫 Gestionar / Bloquear Usuarios", callback_data="manage_users_list")],
        [InlineKeyboardButton("✏️ Cambiar Mensaje de Bienvenida", callback_data="edit_welcome_msg")],
        [InlineKeyboardButton("🔘 Cambiar Texto del Botón Azar", callback_data="edit_btn_text")],
        [InlineKeyboardButton("💬 Editar Botón de Contacto", callback_data="edit_contact_btn")],
        [InlineKeyboardButton("🔙 Volver al inicio", callback_data="back_start")],
    ]
    
    try:
        await query.message.delete()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="🛠️ *Panel de Administración*\n\n"
             "• Para **agregar** una foto nueva, envíamela por aquí con una descripción.\n"
             "• Selecciona una opción abajo para configurar el bot.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# --- CAPTURAR FOTOS NUEVAS ---
async def handle_admin_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID or update.effective_chat.type != "private":
        return

    photo = update.message.photo[-1]
    file_id = photo.file_id
    caption = update.message.caption or ""

    conn = sqlite3.connect("bot_rajona.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO images (file_id, weight, caption) VALUES (?, 1, ?)", (file_id, caption))
    conn.commit()
    conn.close()

    keyboard = [
        [InlineKeyboardButton("⚙️ Abrir Panel de Administración", callback_data="admin_menu")]
    ]
    await update.message.reply_text(
        "✅ ¡Foto agregada con éxito bajo protección contra descargas!\n• Peso por defecto: `1`",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# --- ENVIAR FOTO AL AZAR (Limpia los botones anteriores del usuario) ---
async def send_random_image_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    if is_banned(user.id) and user.id != ADMIN_ID:
        await query.answer("❌ No tienes acceso a este bot.", show_alert=True)
        return

    register_user(user)

    now = time.time()
    last_click = user_cooldowns.get(user.id, 0)
    if now - last_click < 3.0:
        await query.answer("⏳ Espera 3 segundos antes de volver a presionar el botón.", show_alert=True)
        return
    user_cooldowns[user.id] = now

    await query.answer()

    conn = sqlite3.connect("bot_rajona.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, file_id, weight, caption FROM images")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        try:
            await context.bot.send_message(chat_id=user.id, text="⚠️ Aún no hay fotos configuradas.")
        except Exception:
            await query.edit_message_text("⚠️ Háblame primero al privado (/start).")
        return

    file_ids = [row[1] for row in rows]
    weights = [row[2] for row in rows]
    captions = [row[3] for row in rows]

    chosen_file, chosen_caption, chosen_weight = random.choices(
        list(zip(file_ids, captions, weights)), weights=weights, k=1
    )[0]

    btn_text = get_setting("button_text", "🎲 Rajona al azar")
    contact_btn_text = get_setting("contact_btn_text", "💬 Hablar con el Admin")
    contact_link = get_setting("contact_link", f"https://t.me/{ADMIN_USERNAME}")

    keyboard_buttons = [
        [InlineKeyboardButton(btn_text, callback_data="rajona_azur")],
        [InlineKeyboardButton(contact_btn_text, url=contact_link)]
    ]
    if user.id == ADMIN_ID:
        keyboard_buttons.append([InlineKeyboardButton("⚙️ Panel de Administración", callback_data="admin_menu")])

    try:
        # Eliminar el mensaje de botones anterior para que no se acumulen
        try:
            await query.message.delete()
        except Exception:
            pass

        # Enviar foto protegida
        await context.bot.send_photo(
            chat_id=user.id,
            photo=chosen_file,
            caption=chosen_caption if chosen_caption else None,
            protect_content=True 
        )
        
        # Enviar botones nuevos al final
        await context.bot.send_message(
            chat_id=user.id,
            text="¿Quieres otra al azar?",
            reply_markup=InlineKeyboardMarkup(keyboard_buttons)
        )

        if query.message.chat.type != "private":
            await query.answer("¡Te he enviado tu contenido por mensaje privado! 📩", show_alert=True)
    except Exception:
        if query.message.chat.type != "private":
            await query.answer("❌ Tienes que iniciar chat privado conmigo primero (/start).", show_alert=True)

# --- LISTAR Y EDITAR FOTOS ---
async def list_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect("bot_rajona.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, weight, caption FROM images")
    rows = cursor.fetchall()
    conn.close()

    try:
        await query.message.delete()
    except Exception:
        pass

    if not rows:
        keyboard = [[InlineKeyboardButton("🔙 Volver al Panel", callback_data="admin_menu")]]
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="No hay fotos registradas.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    text = "📋 *Gestión de Fotos:*\n\n"
    keyboard = []
    for row in rows:
        img_id, weight, caption = row
        short_caption = (caption[:15] + '...') if len(caption) > 15 else (caption or "Sin texto")
        text += f"🆔 ID: `{img_id}` | ⚖️ Peso: `{weight}` | 💬 {short_caption}\n"
        
        keyboard.append([
            InlineKeyboardButton(f"❌ Borrar {img_id}", callback_data=f"del_{img_id}"),
            InlineKeyboardButton(f"⚖️ Peso ID {img_id}", callback_data=f"editw_{img_id}"),
            InlineKeyboardButton(f"💬 Texto ID {img_id}", callback_data=f"editc_{img_id}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Volver al Panel", callback_data="admin_menu")])
    
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# --- GESTIÓN INTERACTIVA DE USUARIOS RECIENTES ---
async def manage_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect("bot_rajona.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, display_name FROM recent_users LIMIT 15")
    users = cursor.fetchall()
    conn.close()

    try:
        await query.message.delete()
    except Exception:
        pass

    if not users:
        keyboard = [[InlineKeyboardButton("🔙 Volver al Panel", callback_data="admin_menu")]]
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="No hay usuarios recientes registrados aún.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    text = "🚫 *Gestión de Usuarios Recientes*\n\nSelecciona un usuario para bloquearlo o desbloquearlo:\n"
    keyboard = []
    
    for u_id, name in users:
        banned = is_banned(u_id)
        status_icon = "🔴 [Bloqueado]" if banned else "🟢 [Activo]"
        action_data = f"unban_{u_id}" if banned else f"ban_{u_id}"
        action_text = f"🔓 Desbloquear {name}" if banned else f"🚫 Bloquear {name}"
        
        text += f"• {name} (`{u_id}`) {status_icon}\n"
        keyboard.append([InlineKeyboardButton(action_text, callback_data=action_data)])

    keyboard.append([InlineKeyboardButton("🔙 Volver al Panel", callback_data="admin_menu")])
    
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# --- BOTONES Y ACCIONES DEL ADMIN ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "rajona_azur":
        await send_random_image_dm(update, context)
    elif data == "admin_menu":
        await admin_menu(update, context)
    elif data == "back_start":
        try:
            await query.message.delete()
        except Exception:
            pass
        await start(update, context)
    elif data == "list_images":
        await list_images(update, context)
    elif data == "manage_users_list":
        await manage_users_list(update, context)
    elif data.startswith("ban_"):
        b_id = int(data.split("_")[1])
        conn = sqlite3.connect("bot_rajona.db")
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (b_id,))
        conn.commit()
        conn.close()
        await query.answer("¡Usuario bloqueado con éxito!", show_alert=True)
        await manage_users_list(update, context)
    elif data.startswith("unban_"):
        b_id = int(data.split("_")[1])
        conn = sqlite3.connect("bot_rajona.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (b_id,))
        conn.commit()
        conn.close()
        await query.answer("¡Usuario desbloqueado!", show_alert=True)
        await manage_users_list(update, context)
    elif data == "edit_welcome_msg":
        try:
            await query.message.delete()
        except Exception:
            pass
        context.user_data["waiting_for_welcome"] = True
        await context.bot.send_message(chat_id=query.message.chat_id, text="✍️ Envía el **nuevo mensaje de bienvenida**:")
        await query.answer()
    elif data == "edit_btn_text":
        try:
            await query.message.delete()
        except Exception:
            pass
        context.user_data["waiting_for_button"] = True
        await context.bot.send_message(chat_id=query.message.chat_id, text="✍️ Envía el **nuevo texto para el botón de azar**:")
        await query.answer()
    elif data == "edit_contact_btn":
        try:
            await query.message.delete()
        except Exception:
            pass
        context.user_data["waiting_for_contact_text"] = True
        await context.bot.send_message(chat_id=query.message.chat_id, text="✍️ Envía primero el **nuevo texto del botón de contacto**:")
        await query.answer()
    elif data.startswith("del_"):
        img_id = data.split("_")[1]
        conn = sqlite3.connect("bot_rajona.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM images WHERE id = ?", (img_id,))
        conn.commit()
        conn.close()
        await query.answer("¡Foto eliminada!")
        await list_images(update, context)
    elif data.startswith("editw_"):
        try:
            await query.message.delete()
        except Exception:
            pass
        img_id = data.split("_")[1]
        context.user_data["editing_weight_id"] = img_id
        await context.bot.send_message(chat_id=query.message.chat_id, text=f"✍️ Escribe el nuevo **número de peso** para la imagen ID {img_id}:", parse_mode="Markdown")
        await query.answer()
    elif data.startswith("editc_"):
        try:
            await query.message.delete()
        except Exception:
            pass
        img_id = data.split("_")[1]
        context.user_data["editing_caption_id"] = img_id
        await context.bot.send_message(chat_id=query.message.chat_id, text=f"✍️ Escribe el **nuevo texto** para la imagen ID {img_id}:", parse_mode="Markdown")
        await query.answer()

# --- MANEJADOR DE TEXTO PARA MODIFICACIONES ---
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID or update.effective_chat.type != "private":
        return

    text = update.message.text
    chat_id = update.message.chat_id

    async def send_panel_return():
        keyboard = [[InlineKeyboardButton("⚙️ Volver al Panel de Administración", callback_data="admin_menu")]]
        await context.bot.send_message(chat_id=chat_id, text="¿Qué deseas hacer ahora?", reply_markup=InlineKeyboardMarkup(keyboard))

    if context.user_data.get("waiting_for_welcome"):
        set_setting("welcome_message", text)
        del context.user_data["waiting_for_welcome"]
        await update.message.reply_text("✅ ¡Mensaje de bienvenida actualizado!")
        await send_panel_return()

    elif context.user_data.get("waiting_for_button"):
        set_setting("button_text", text)
        del context.user_data["waiting_for_button"]
        await update.message.reply_text("✅ ¡Texto del botón de azar actualizado!")
        await send_panel_return()

    elif context.user_data.get("waiting_for_contact_text"):
        context.user_data["contact_btn_text_temp"] = text
        context.user_data["waiting_for_contact_text"] = False
        context.user_data["waiting_for_contact_link"] = True
        await update.message.reply_text("🔗 Ahora envía el **enlace de Telegram** (ejemplo: `https://t.me/Demboy_chile`):", parse_mode="Markdown")

    elif context.user_data.get("waiting_for_contact_link"):
        btn_txt = context.user_data.get("contact_btn_text_temp", "💬 Hablar con el Admin")
        set_setting("contact_btn_text", btn_txt)
        set_setting("contact_link", text)
        del context.user_data["waiting_for_contact_link"]
        await update.message.reply_text("✅ ¡Botón de contacto y enlace actualizados con éxito!")
        await send_panel_return()

    elif "editing_weight_id" in context.user_data:
        img_id = context.user_data["editing_weight_id"]
        try:
            new_weight = int(text)
            conn = sqlite3.connect("bot_rajona.db")
            cursor = conn.cursor()
            cursor.execute("UPDATE images SET weight = ? WHERE id = ?", (new_weight, img_id))
            conn.commit()
            conn.close()
            
            del context.user_data["editing_weight_id"]
            await update.message.reply_text(f"✅ ¡Peso actualizado a `{new_weight}`!", parse_mode="Markdown")
            await send_panel_return()
        except ValueError:
            await update.message.reply_text("⚠️ Introduce un número entero válido.")

    elif "editing_caption_id" in context.user_data:
        img_id = context.user_data["editing_caption_id"]
        new_caption = "" if text.lower() == "ninguno" else text
        
        conn = sqlite3.connect("bot_rajona.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE images SET caption = ? WHERE id = ?", (new_caption, img_id))
        conn.commit()
        conn.close()
        
        del context.user_data["editing_caption_id"]
        await update.message.reply_text("✅ ¡Texto actualizado!")
        await send_panel_return()

async def panel_grupo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    btn_text = get_setting("button_text", "🎲 Rajona al azar")
    contact_btn_text = get_setting("contact_btn_text", "💬 Hablar con el Admin")
    contact_link = get_setting("contact_link", f"https://t.me/{ADMIN_USERNAME}")
    
    keyboard = [
        [InlineKeyboardButton(btn_text, callback_data="rajona_azur")],
        [InlineKeyboardButton(contact_btn_text, url=contact_link)]
    ]
    await update.message.reply_text("Panel interactivo de Rajona:", reply_markup=InlineKeyboardMarkup(keyboard))

def main():
    keep_alive()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel_grupo))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, handle_admin_photo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND) & filters.ChatType.PRIVATE, text_handler))
    
    print("Bot corriendo...")
    app.run_polling()

if __name__ == "__main__":
    main()
