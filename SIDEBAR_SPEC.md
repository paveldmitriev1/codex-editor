# SIDEBAR_SPEC.md — Спецификация левого и правого сайдбаров

**Назначение:** описывает левый и правый сайдбары приложения «Кодекс» точно по образцу claude.ai. Используется вместе с `CLAUDE_DESIGN_REFERENCE.md`.

---

## 1. Общая концепция

Приложение «Кодекс» имеет **два сайдбара**:
- **Левый** — основная навигация: разделы приложения + список глав/документов.
- **Правый** — контекстная панель: источники, связанные документы, метаданные текущей страницы.

Оба:
- **Сворачиваемы** через кнопку-toggle. Свёрнутый = 40-48px с иконкой. Развёрнутый = 260px (правый 280px).
- **Одинаковый визуальный язык** — те же фоны, шрифты, размеры, паттерны.
- **Состояние в localStorage** между сессиями.

---

## 2. Левый сайдбар

### 2.1. Шапка (56px высота)

- Логотип «Кодекс» — sans-serif Inter, font-weight 600, размер 18-20px, цвет `--color-text-primary`.
- Кнопка-toggle справа: Lucide `panel-left-close` (раскрыт) / `panel-left-open` (свёрнут). 20px иконка в обёртке 32×32px, radius 8px, hover bg `--color-bg-muted`.
- **Никаких других стрелок** `‹›` сбоку — только эта кнопка.
- Padding: `12px 16px`.

### 2.2. Главное меню — пункт = иконка + текст

```css
.sidebar-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border-radius: var(--radius-md);
  font-size: 15px;
  font-weight: var(--font-weight-regular);
  color: var(--color-text-primary);
  height: 36px;
}
.sidebar-item__icon {
  width: 20px;
  height: 20px;
  stroke-width: 1.75;
  color: var(--color-text-secondary);
}
.sidebar-item:hover {
  background: var(--color-bg-muted);
}
.sidebar-item--active {
  background: var(--color-bg-muted);   /* СЕРЫЙ, не цветной */
  font-weight: var(--font-weight-medium);
}
```

**Важное:** активный пункт = **серый фон `--color-bg-muted`**, такой же как hover. Без цветных подсветок. Это паттерн claude.ai.

### 2.3. Маппинг иконок Lucide для «Кодекса»

| Пункт меню            | Lucide-иконка       |
|-----------------------|---------------------|
| Новая глава с нуля    | `plus`              |
| Поиск                 | `search`            |
| Оглавление            | `book-open`         |
| Редактор              | `pen-line`          |
| Утренний брифинг      | `sun`               |
| Хранилище             | `archive`           |
| Компоненты (dev)      | `palette`           |

Все 20px, `stroke-width: 1.75`, цвет наследуется.

### 2.4. Группы и разделители

```css
.sidebar-group-label {
  font-size: 12px;
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
  padding: 8px 12px 4px;
  letter-spacing: 0;        /* НЕ UPPERCASE */
}
```

Лейблы: `Starred`, `Главы`, `Документы` — обычный регистр.

### 2.5. Элементы списка (главы)

```css
.sidebar-list-item {
  display: flex;
  justify-content: space-between;
  padding: 8px 12px;
  border-radius: var(--radius-md);
  font-size: 14px;
  height: 32px;
}
.sidebar-list-item__text {
  text-overflow: ellipsis;    /* длинные → "..." */
}
.sidebar-list-item__menu {
  /* троеточие справа, появляется только на hover */
  opacity: 0;
  width: 20px;
  height: 20px;
}
.sidebar-list-item:hover .sidebar-list-item__menu,
.sidebar-list-item--active .sidebar-list-item__menu {
  opacity: 1;
}
```

### 2.6. Профиль внизу

```
┌─────────────────────────────────┐
│ [П]  Pavel              [⬇] [⇅] │
│      Хилингод                   │
└─────────────────────────────────┘
```

- Аватар-круг 32×32px, фон `--color-text-primary`, белая буква «П», font-weight 600.
- Имя `Pavel` — 14px medium.
- Подпись `Хилингод` — 12px muted.
- Прижато к низу: `position: sticky; bottom: 0`.
- Граница сверху: `border-top: 1px solid var(--color-border)`.

### 2.7. Геометрия

- **Развёрнутый: 260px**
- **Свёрнутый: 56px** (только иконки разделов, текст скрыт, список глав скрыт)
- **Фон:** `var(--color-bg-app)` — тёплый кремовый, **не белый**.
- **Граница справа:** `1px solid var(--color-border)` или вовсе нет (на claude.ai почти не видна).

---

## 3. Правый сайдбар

### 3.1. Структура

```
┌─────────────────────────────────┐
│  Контекст              [⊟]      │
├─────────────────────────────────┤
│  Источники                      │
│   • file-1.md            [⋯]   │
│   • file-2.md            [⋯]   │
│                                 │
│  Связанные главы                │
│   • Глава 6              [⋯]   │
│   • Глава 8              [⋯]   │
│                                 │
│  Метаданные                     │
│   parag.    122                 │
│   chars     35K                 │
└─────────────────────────────────┘
```

### 3.2. Метаданные

```css
.metadata-list {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 16px;
}
.metadata-list__label {
  font-size: 12px;
  color: var(--color-text-muted);
}
.metadata-list__value {
  font-size: 13px;
  color: var(--color-text-primary);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
```

### 3.3. Геометрия

- **Развёрнутый: 280px**
- **Свёрнутый: 48px** (только кнопка разворачивания)
- **Граница слева:** `1px solid var(--color-border)`
- **Фон:** `var(--color-bg-app)`

---

## 4. Поведение сворачивания

### 4.1. Анимация
- Длительность: **150ms**, easing `ease-out`.
- Анимируется только `width`.
- Контент внутри — `opacity` 100ms.

### 4.2. localStorage
```javascript
localStorage.setItem('kodeks.sidebar.left.collapsed', 'true' | 'false');
localStorage.setItem('kodeks.sidebar.right.collapsed', 'true' | 'false');
```

### 4.3. Горячие клавиши
- `Cmd/Ctrl + B` — toggle левого
- `Cmd/Ctrl + Shift + B` — toggle правого

---

## 5. Layout приложения

```
┌──────────────────────────────────────────────────────────┐
│ Left (260/56) │  Main (flex: 1)        │ Right (280/48)  │
└──────────────────────────────────────────────────────────┘
```

```css
.app-shell {
  display: flex;
  height: 100vh;
  background: var(--color-bg-app);
}
.app-shell__sidebar-left {
  width: 260px;
  flex-shrink: 0;
  transition: width 150ms ease-out;
  border-right: 1px solid var(--color-border);
}
.app-shell__sidebar-left--collapsed { width: 56px; }
.app-shell__main { flex: 1; overflow-y: auto; min-width: 0; }
.app-shell__sidebar-right {
  width: 280px;
  flex-shrink: 0;
  transition: width 150ms ease-out;
  border-left: 1px solid var(--color-border);
}
.app-shell__sidebar-right--collapsed { width: 48px; }
```

---

## 6. Анти-паттерны (то, что есть в «Кодексе» и надо убрать)

- ❌ Узкая полоска с `‹` между сайдбаром и контентом. Убрать.
- ❌ Чёрные капсулы (`rewrite главы`, `Полный rewrite 14`). Заменить на `.sidebar-list-item` и `<Button>`.
- ❌ Floating action button в правом нижнем углу. Убрать.
- ❌ Цветные акценты в активном пункте. Только серый.
- ❌ Иконки разных стилей. Только Lucide stroke-width 1.75.
- ❌ Резкие прыжки сворачивания. Плавная анимация 150ms.

---

## 7. Чек-лист

- [ ] Левый sidebar 260/56px, активный = серый
- [ ] Lucide иконки stroke-width 1.75 (20px в меню)
- [ ] Группы — обычный регистр, не UPPERCASE
- [ ] Длинные названия с `...`
- [ ] Троеточие на hover/active
- [ ] Профиль с аватаром-кругом внизу
- [ ] Свёрнутый sidebar 56px с tooltip
- [ ] Правый sidebar 280/48px
- [ ] Анимация 150ms плавная
- [ ] localStorage для состояния
- [ ] Cmd+B / Cmd+Shift+B горячие
- [ ] Нет торчащей кнопки `‹`
