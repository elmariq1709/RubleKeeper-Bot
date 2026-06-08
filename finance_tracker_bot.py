import logging
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, ConversationHandler
)
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
from io import BytesIO
import os

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния диалога
ADD_EXPENSE = 1
ADD_INCOME = 2
SET_BUDGET = 3
CHOOSE_CATEGORY = 4
CHOOSE_REPORT_TYPE = 5

# Категории расходов
CATEGORIES = {
    "🍽️": "Еда",
    "🚗": "Транспорт",
    "🎮": "Развлечения",
    "🏠": "Счета",
    "🏥": "Здоровье",
    "🛍️": "Покупки",
    "❓": "Другое"
}

# Инициализация БД
def init_db():
    """Инициализирует базу данных"""
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, username TEXT, monthly_budget REAL DEFAULT 0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS transactions
                 (id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL, 
                  type TEXT, category TEXT, date TIMESTAMP, description TEXT)''')
    
    conn.commit()
    conn.close()

def get_user(user_id):
    """Получает или создает пользователя"""
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = c.fetchone()
    
    if not user:
        c.execute('INSERT INTO users (user_id) VALUES (?)', (user_id,))
        conn.commit()
    
    conn.close()
    return user

def add_transaction(user_id, amount, trans_type, category, description=""):
    """Добавляет транзакцию"""
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    
    now = datetime.now()
    c.execute('''INSERT INTO transactions (user_id, amount, type, category, date, description)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (user_id, amount, trans_type, category, now, description))
    
    conn.commit()
    conn.close()

def get_balance(user_id):
    """Получает текущий баланс"""
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    
    c.execute('''SELECT SUM(CASE WHEN type='income' THEN amount ELSE -amount END)
                 FROM transactions WHERE user_id = ?''', (user_id,))
    
    result = c.fetchone()[0]
    conn.close()
    
    return result if result else 0

def get_monthly_budget(user_id):
    """Получает месячный бюджет"""
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    
    c.execute('SELECT monthly_budget FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    
    conn.close()
    return result[0] if result else 0

def set_monthly_budget(user_id, budget):
    """Устанавливает месячный бюджет"""
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    
    c.execute('UPDATE users SET monthly_budget = ? WHERE user_id = ?', (budget, user_id))
    
    conn.commit()
    conn.close()

def get_transactions(user_id, days=None):
    """Получает транзакции за последние дни (или все если days=None)"""
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    
    if days:
        date_from = datetime.now() - timedelta(days=days)
        c.execute('''SELECT * FROM transactions WHERE user_id = ? AND date >= ?
                     ORDER BY date DESC''', (user_id, date_from))
    else:
        c.execute('SELECT * FROM transactions WHERE user_id = ? ORDER BY date DESC', (user_id,))
    
    transactions = c.fetchall()
    conn.close()
    
    return transactions

def get_expenses_by_category(user_id, days=None):
    """Получает расходы по категориям"""
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    
    if days:
        date_from = datetime.now() - timedelta(days=days)
        c.execute('''SELECT category, SUM(amount) FROM transactions 
                     WHERE user_id = ? AND type = 'expense' AND date >= ?
                     GROUP BY category''', (user_id, date_from))
    else:
        c.execute('''SELECT category, SUM(amount) FROM transactions 
                     WHERE user_id = ? AND type = 'expense'
                     GROUP BY category''', (user_id,))
    
    result = c.fetchall()
    conn.close()
    
    return result

def format_balance_message(user_id):
    """Форматирует сообщение с балансом"""
    balance = get_balance(user_id)
    budget = get_monthly_budget(user_id)
    
    # Получаем расходы за текущий месяц
    now = datetime.now()
    month_start = datetime(now.year, now.month, 1)
    
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    c.execute('''SELECT SUM(amount) FROM transactions 
                 WHERE user_id = ? AND type = 'expense' AND date >= ?''',
              (user_id, month_start))
    
    month_expenses = c.fetchone()[0] or 0
    conn.close()
    
    message = f"💰 <b>ВАШ ФИНАНСОВЫЙ СТАТУС</b>\n\n"
    message += f"💵 Баланс: <b>{balance:.2f} ₽</b>\n"
    
    if budget > 0:
        remaining = budget - month_expenses
        percentage = (month_expenses / budget * 100) if budget > 0 else 0
        
        message += f"📊 Месячный бюджет: <b>{budget:.2f} ₽</b>\n"
        message += f"📉 Расходы в этом месяце: <b>{month_expenses:.2f} ₽</b>\n"
        message += f"📈 Осталось: <b>{remaining:.2f} ₽</b> ({100-percentage:.0f}%)\n"
        
        if remaining < 0:
            message += f"\n⚠️ <b>Бюджет превышен на {abs(remaining):.2f} ₽!</b>\n"
    else:
        message += f"\n⚠️ Бюджет не установлен (используйте /set_budget)\n"
    
    return message

def create_pie_chart(user_id, days=None):
    """Создает круговую диаграмму расходов по категориям"""
    expenses = get_expenses_by_category(user_id, days)
    
    if not expenses:
        return None
    
    categories = [e[0] for e in expenses]
    amounts = [e[1] for e in expenses]
    
    # Преобразуем коды в названия
    labels = [f"{list(CATEGORIES.values())[list(CATEGORIES.values()).index(cat)] if cat in CATEGORIES.values() else cat}" 
              for cat in categories]
    
    fig, ax = plt.subplots(figsize=(10, 8))
    colors = plt.cm.Set3(range(len(labels)))
    
    wedges, texts, autotexts = ax.pie(amounts, labels=labels, autopct='%1.1f%%',
                                       colors=colors, startangle=90)
    
    for autotext in autotexts:
        autotext.set_color('black')
        autotext.set_fontsize(10)
        autotext.set_weight('bold')
    
    ax.set_title('Расходы по категориям', fontsize=14, fontweight='bold')
    
    buf = BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', dpi=100)
    buf.seek(0)
    plt.close()
    
    return buf

def create_bar_chart(user_id, days=7):
    """Создает столбчатую диаграмму расходов по дням"""
    transactions = get_transactions(user_id, days)
    
    if not transactions:
        return None
    
    # Группируем по дням
    daily_data = {}
    for t in transactions:
        date = datetime.fromisoformat(t[5]).date()
        if date not in daily_data:
            daily_data[date] = {'income': 0, 'expense': 0}
        
        if t[3] == 'income':
            daily_data[date]['income'] += t[2]
        else:
            daily_data[date]['expense'] += t[2]
    
    dates = sorted(daily_data.keys())
    incomes = [daily_data[d]['income'] for d in dates]
    expenses = [daily_data[d]['expense'] for d in dates]
    
    x = range(len(dates))
    fig, ax = plt.subplots(figsize=(12, 6))
    
    ax.bar([i - 0.2 for i in x], incomes, 0.4, label='Доходы', color='green', alpha=0.7)
    ax.bar([i + 0.2 for i in x], expenses, 0.4, label='Расходы', color='red', alpha=0.7)
    
    ax.set_xlabel('Дата', fontweight='bold')
    ax.set_ylabel('Сумма (₽)', fontweight='bold')
    ax.set_title('Доходы и расходы по дням', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels([d.strftime('%d.%m') for d in dates], rotation=45)
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    
    buf = BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', dpi=100)
    buf.seek(0)
    plt.close()
    
    return buf

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    get_user(user_id)
    
    keyboard = [
        [InlineKeyboardButton("➕ Добавить расход", callback_data='add_expense'),
         InlineKeyboardButton("➕ Добавить доход", callback_data='add_income')],
        [InlineKeyboardButton("💰 Показать баланс", callback_data='show_balance'),
         InlineKeyboardButton("📊 Отчёты", callback_data='reports')],
        [InlineKeyboardButton("💵 Установить бюджет", callback_data='set_budget')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👋 Добро пожаловать в <b>Финансовый Трекер</b>! 💰\n\n"
        "Я помогу вам отслеживать доходы и расходы, анализировать траты и управлять бюджетом.\n\n"
        "Что вы хотите сделать?",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает баланс"""
    query = update.callback_query
    user_id = query.from_user.id
    
    message = format_balance_message(user_id)
    
    keyboard = [
        [InlineKeyboardButton("⬅️ Назад", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode="HTML")

async def reports_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню отчётов"""
    query = update.callback_query
    
    keyboard = [
        [InlineKeyboardButton("📅 Отчёт за день", callback_data='report_day')],
        [InlineKeyboardButton("📊 Отчёт за неделю", callback_data='report_week')],
        [InlineKeyboardButton("📈 Отчёт за месяц", callback_data='report_month')],
        [InlineKeyboardButton("🥧 График расходов", callback_data='report_pie')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='back')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📊 <b>ОТЧЁТЫ</b>\n\nВыберите период:",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

async def generate_report(update: Update, context: ContextTypes.DEFAULT_TYPE, days=None, report_type='text'):
    """Генерирует отчёт"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if report_type == 'pie':
        # График по категориям за месяц
        buf = create_pie_chart(user_id, 30)
        if buf:
            await query.message.reply_photo(buf, caption="📊 Расходы по категориям за месяц")
        else:
            await query.answer("Нет данных для графика", show_alert=True)
        
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data='back')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_reply_markup(reply_markup)
        return
    
    elif report_type == 'bar':
        # График доходов/расходов по дням
        buf = create_bar_chart(user_id, days if days else 7)
        if buf:
            await query.message.reply_photo(buf, caption=f"📈 Доходы и расходы за последние {days or 7} дней")
        else:
            await query.answer("Нет данных для графика", show_alert=True)
        
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data='back')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_reply_markup(reply_markup)
        return
    
    # Текстовый отчёт
    transactions = get_transactions(user_id, days)
    
    if not transactions:
        await query.answer("Нет данных за этот период", show_alert=True)
        return
    
    total_income = sum(t[2] for t in transactions if t[3] == 'income')
    total_expense = sum(t[2] for t in transactions if t[3] == 'expense')
    
    if days == 1:
        period = "за сегодня"
    elif days == 7:
        period = "за неделю"
    elif days == 30:
        period = "за месяц"
    else:
        period = "всего"
    
    message = f"📊 <b>ОТЧЁТ {period.upper()}</b>\n\n"
    message += f"✅ Доходы: <b>{total_income:.2f} ₽</b>\n"
    message += f"❌ Расходы: <b>{total_expense:.2f} ₽</b>\n"
    message += f"💹 Итого: <b>{total_income - total_expense:.2f} ₽</b>\n\n"
    
    message += "<b>📝 Транзакции:</b>\n\n"
    
    for t in transactions[:10]:  # Показываем последние 10
        date = datetime.fromisoformat(t[5]).strftime('%d.%m %H:%M')
        icon = "✅" if t[3] == 'income' else "❌"
        message += f"{icon} {date} | {t[4]}: <b>{t[2]:.2f} ₽</b>\n"
    
    if len(transactions) > 10:
        message += f"\n... и ещё {len(transactions) - 10} транзакций"
    
    keyboard = [
        [InlineKeyboardButton("📊 График по дням", callback_data='report_bar_7')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode="HTML")

async def add_expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает процесс добавления расхода"""
    query = update.callback_query
    
    keyboard = [
        [InlineKeyboardButton(f"{emoji} {CATEGORIES[emoji]}", callback_data=f'cat_{emoji}')]
        for emoji in CATEGORIES.keys()
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='back')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📁 <b>ВЫБЕРИТЕ КАТЕГОРИЮ РАСХОДА:</b>",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    
    context.user_data['transaction_type'] = 'expense'
    return CHOOSE_CATEGORY

async def add_income_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает процесс добавления дохода"""
    query = update.callback_query
    
    await query.edit_message_text(
        "💵 <b>ДОБАВИТЬ ДОХОД</b>\n\n"
        "Введите сумму доход (только цифры):\n\n"
        "Например: <code>5000</code>",
        parse_mode="HTML"
    )
    
    context.user_data['transaction_type'] = 'income'
    return ADD_INCOME

async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора категории"""
    query = update.callback_query
    
    category_emoji = query.data.split('_')[1]
    context.user_data['category'] = CATEGORIES[category_emoji]
    
    await query.edit_message_text(
        f"💰 <b>ДОБАВИТЬ РАСХОД</b>\n\n"
        f"Категория: <b>{CATEGORIES[category_emoji]}</b>\n\n"
        f"Введите сумму расхода (только цифры):\n\n"
        f"Например: <code>350</code>",
        parse_mode="HTML"
    )
    
    return ADD_EXPENSE

async def amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ввода суммы"""
    try:
        amount = float(update.message.text.replace(',', '.'))
        
        if amount <= 0:
            await update.message.reply_text("❌ Сумма должна быть больше 0!")
            return ADD_EXPENSE if context.user_data.get('transaction_type') == 'expense' else ADD_INCOME
        
        user_id = update.effective_user.id
        trans_type = context.user_data.get('transaction_type')
        category = context.user_data.get('category', 'Доход')
        
        add_transaction(user_id, amount, trans_type, category)
        
        await update.message.reply_text(
            f"✅ <b>{category}</b> на сумму <b>{amount:.2f} ₽</b> добавлен(а)!",
            parse_mode="HTML"
        )
        
        # Показываем баланс
        message = format_balance_message(user_id)
        
        keyboard = [
            [InlineKeyboardButton("➕ Добавить ещё", callback_data='add_expense' if trans_type == 'expense' else 'add_income'),
             InlineKeyboardButton("💰 Баланс", callback_data='show_balance')],
            [InlineKeyboardButton("📊 Отчёты", callback_data='reports'),
             InlineKeyboardButton("⬅️ Главное меню", callback_data='back')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="HTML")
        
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("❌ Введите корректную сумму (только цифры)")
        return ADD_EXPENSE if context.user_data.get('transaction_type') == 'expense' else ADD_INCOME

async def set_budget_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает процесс установки бюджета"""
    query = update.callback_query
    
    current_budget = get_monthly_budget(query.from_user.id)
    
    message = f"💵 <b>УСТАНОВИТЬ МЕСЯЧНЫЙ БЮДЖЕТ</b>\n\n"
    if current_budget > 0:
        message += f"Текущий бюджет: <b>{current_budget:.2f} ₽</b>\n\n"
    
    message += "Введите желаемый месячный бюджет (только цифры):\n\n" \
              "Например: <code>50000</code>"
    
    await query.edit_message_text(message, parse_mode="HTML")
    
    return SET_BUDGET

async def budget_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ввода бюджета"""
    try:
        budget = float(update.message.text.replace(',', '.'))
        
        if budget <= 0:
            await update.message.reply_text("❌ Бюджет должен быть больше 0!")
            return SET_BUDGET
        
        user_id = update.effective_user.id
        set_monthly_budget(user_id, budget)
        
        await update.message.reply_text(
            f"✅ <b>Месячный бюджет установлен: {budget:.2f} ₽</b>",
            parse_mode="HTML"
        )
        
        # Показываем баланс
        message = format_balance_message(user_id)
        
        keyboard = [
            [InlineKeyboardButton("⬅️ Главное меню", callback_data='back')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="HTML")
        
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("❌ Введите корректную сумму (только цифры)")
        return SET_BUDGET

async def back_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки 'Назад'"""
    query = update.callback_query
    user_id = query.from_user.id
    
    keyboard = [
        [InlineKeyboardButton("➕ Добавить расход", callback_data='add_expense'),
         InlineKeyboardButton("➕ Добавить доход", callback_data='add_income')],
        [InlineKeyboardButton("💰 Показать баланс", callback_data='show_balance'),
         InlineKeyboardButton("📊 Отчёты", callback_data='reports')],
        [InlineKeyboardButton("💵 Установить бюджет", callback_data='set_budget')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = format_balance_message(user_id)
    
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode="HTML")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает все callback кнопки"""
    query = update.callback_query
    data = query.data
    
    await query.answer()
    
    if data == 'back':
        await back_button(update, context)
    elif data == 'show_balance':
        await show_balance(update, context)
    elif data == 'reports':
        await reports_menu(update, context)
    elif data == 'report_day':
        await generate_report(update, context, days=1)
    elif data == 'report_week':
        await generate_report(update, context, days=7, report_type='bar')
    elif data == 'report_month':
        await generate_report(update, context, days=30)
    elif data == 'report_pie':
        await generate_report(update, context, days=30, report_type='pie')
    elif data == 'report_bar_7':
        await generate_report(update, context, days=7, report_type='bar')
    elif data == 'add_expense':
        return await add_expense_start(update, context)
    elif data == 'add_income':
        return await add_income_start(update, context)
    elif data == 'set_budget':
        return await set_budget_start(update, context)
    elif data.startswith('cat_'):
        return await category_selected(update, context)

def main():
    """Запускает бота"""
    
    init_db()
    
    # ЗАМЕНИТЕ НА ВАШ ТОКЕН!
    TOKEN = "8745855289:AAG8IhQbJ4djiChC8uT5qQTL2OWg4t3qQmQ"
    
    application = Application.builder().token(TOKEN).build()
    
    # Обработчик главного меню
    application.add_handler(CommandHandler("start", start))
    
    # Callback обработчик
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    # Обработчики текстового ввода
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, amount_input))
    
    print("🤖 Финансовый трекер запущен! Нажмите Ctrl+C для остановки.")
    application.run_polling()

if __name__ == '__main__':
    main()
