# CLAUDE_DESIGN_REFERENCE.md

**Назначение:** этот документ — единственный источник истины по визуальному языку приложения «Кодекс». Он описывает дизайн в стиле claude.ai / Anthropic, на который мы равняемся.

**Приоритет:** этот документ важнее, чем `DESIGN_SYSTEM.md`. При расхождениях побеждает этот файл.

**Источники:** официальный бренд-гайд Anthropic + визуальная инспекция интерфейса claude.ai.

**Решение Pavel-а 2026-05-21:** выбран **Вариант Б** — фиолетовый акцент `#6366F1` сохраняем (своя айдентика Кодекса), всё остальное — типографика, фон, серые, sidebar-паттерны — приводим к стилю claude.ai.

---

## 1. Философия дизайна Claude.ai

Прежде чем токены — общие принципы. Их нужно держать в голове при любом UI-решении.

### 1.1. Сдержанность

Claude.ai сделан как рабочий инструмент для думающих людей, а не как «современная нейросеть с эффектами». Это значит:

- Никаких градиентов на фонах. Только плоские цвета.
- Никаких декоративных иллюстраций без функционального смысла.
- Никаких эмодзи в UI.
- Никаких неоновых акцентов, теней с цветом, glow-эффектов.
- Никаких анимаций ради анимаций. Только функциональные переходы (hover, focus, появление модалок) — короткие, спокойные.

### 1.2. Тёплая нейтральность

Дизайн Anthropic не холодный технологический. Он тёплый, бумажный, библиотечный. Основные принципы:

- Фон — off-white (тёплый кремово-белый `#faf9f5`), не чисто белый и не серый.
- Текст — почти чёрный (`#141413`), но не `#000000`.
- Серые — тёплые (с примесью бежевого), а не холодные синеватые.
- Акцент — фиолетовый `#6366F1` (Вариант Б для «Кодекса»). В оригинальном claude.ai акцент — тёплый ржавый оранжевый `#d97757`. Pavel выбрал фиолетовый как свою айдентику.

### 1.3. Типографическая иерархия, а не визуальная

В дизайне claude.ai структура страницы выстраивается **размером и весом шрифта**, а не цветными плашками, рамками или иконками. Это значит:

- Заголовки разделов — крупнее и жирнее, без цветного фона.
- Подразделы — мельче, без рамок.
- Визуальные разделители — тонкие серые линии или просто отступ. Не цветные блоки.

### 1.4. Воздух с ограничениями

Дизайн Claude — просторный, но не пустой. Это разный режим:

- **Просторный** — означает достаточный padding в карточках, line-height 1.5–1.7 для текста, отступы между разделами.
- **НЕ означает:** огромные пустые поля по бокам экрана, карточки на 30% доступной ширины, по 200px пустоты между блоками.

Правило большого пальца: если можно убрать 30% вертикального пустого пространства, не нарушив дыхания — убери.

---

## 2. Палитра — точные значения

```css
:root {
  /* Surfaces — тёплые, бумажные */
  --color-bg-app:        #faf9f5;   /* фон всего приложения */
  --color-bg-surface:    #ffffff;   /* карточки, сайдбар (поверх тёплого фона) */
  --color-bg-subtle:     #f5f4ee;   /* вторичные блоки, выделенные цитаты */
  --color-bg-muted:      #e8e6dc;   /* фон неактивных pill-кнопок, hover-состояния, активный nav-item */

  /* Text — почти чёрный с тёплым подтоном */
  --color-text-primary:  #141413;
  --color-text-secondary:#3d3d3a;
  --color-text-muted:    #6b6b66;
  --color-text-disabled: #b0aea5;

  /* Accent — фиолетовый (Вариант Б, выбор Pavel) */
  --color-accent:        #6366F1;
  --color-accent-hover:  #4F46E5;
  --color-accent-soft:   #EEF0FF;   /* фон фокус-состояний, не активного nav-item */
  --color-accent-text:   #4338CA;

  /* Status — приглушённые */
  --color-success:       #788c5d;
  --color-success-soft:  #eef2e6;
  --color-warning:       #c89344;
  --color-warning-soft:  #faf0dc;
  --color-danger:        #b85540;
  --color-danger-soft:   #faebe5;

  /* Borders */
  --color-border:        #e8e6dc;
  --color-border-strong: #c8c6b8;
}
```

**Что критически важно:**
1. Фон **не** серый `#F4F4F6`, а тёплый кремовый `#faf9f5`. Это сразу даёт «бумажное» ощущение.
2. Текст **не** чёрный `#000`, а почти чёрный `#141413`. Это снимает резкость.
3. Серые **тёплые** (с бежевым оттенком), а не холодные.
4. **Активный пункт sidebar = `--color-bg-muted` (серый)**, не `--color-accent-soft`. См. claude.ai — там активный пункт серый, не цветной.

---

## 3. Типографика

### 3.1. Шрифты

```css
:root {
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-serif: 'Lora', Georgia, 'Times New Roman', serif;  /* ТОЛЬКО для контента глав */
  --font-mono: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
}
```

**Где что:**
- **UI приложения** (вся обвязка): Inter sans-serif. Никаких serif.
- **Контент главы** (длинный читаемый текст в редакторе): Lora serif — для читаемости.
- **Технические идентификаторы** (slugs, hashes, tokens): JetBrains Mono.

### 3.2. Размеры — компактнее, чем кажется новичку

```css
:root {
  --font-size-h1:      28px;   /* заголовок страницы. НЕ 32, НЕ 48. */
  --font-size-h2:      20px;   /* заголовок раздела внутри карточки */
  --font-size-h3:      17px;
  --font-size-h4:      15px;
  --font-size-body:    15px;
  --font-size-small:   13px;
  --font-size-caption: 12px;
  --font-size-micro:   11px;
}
```

**Критически важно:**
- Заголовки в claude.ai меньше, чем кажется. Это 28px, а не 48px.
- UPPERCASE используется **только** для маленьких eyebrow-labels (12px). Никогда для крупных заголовков.

### 3.3. Веса и интерлиньяж

```css
:root {
  --font-weight-regular:  400;
  --font-weight-medium:   500;
  --font-weight-semibold: 600;
  --font-weight-bold:     700;

  --line-height-tight:   1.25;
  --line-height-normal:  1.5;
  --line-height-relaxed: 1.7;   /* для длинных текстов глав */

  --letter-spacing-tight:  -0.01em;
  --letter-spacing-normal: 0;
  --letter-spacing-wide:   0.06em;   /* для UPPERCASE eyebrow-labels */
}
```

---

## 4. Spacing, радиусы, тени

### 4.1. Spacing — компактнее

```css
:root {
  --space-3xs: 2px;
  --space-2xs: 4px;
  --space-xs:  6px;
  --space-sm:  10px;
  --space-md:  14px;
  --space-lg:  20px;
  --space-xl:  28px;   /* внутренний padding карточки */
  --space-2xl: 40px;
  --space-3xl: 56px;
}
```

На claude.ai padding кнопок и табов — `8-12px`, а не `16-24px`.

### 4.2. Радиусы

```css
:root {
  --radius-sm:   6px;
  --radius-md:   8px;     /* кнопки. НЕ 12. */
  --radius-lg:   12px;    /* карточки */
  --radius-xl:   16px;    /* крупные блоки */
  --radius-full: 9999px;  /* pill */
}
```

Дизайн claude.ai **не «пузырный»**. Радиусы умеренные.

### 4.3. Тени

```css
:root {
  --shadow-xs: 0 1px 2px rgba(20, 20, 19, 0.04);
  --shadow-sm: 0 2px 4px rgba(20, 20, 19, 0.05);
  --shadow-md: 0 4px 12px rgba(20, 20, 19, 0.06);
  --shadow-lg: 0 12px 24px rgba(20, 20, 19, 0.08);
}
```

На claude.ai карточки отделены **только тонкой границей** `1px solid var(--color-border)` без тени. Тени — только для модалок/поповеров.

---

## 5. Компоненты

### 5.1. Кнопки — высота 36px, padding `8px 16px`, radius 8px

```css
.button-primary {
  background: var(--color-accent);
  color: white;
  padding: 8px 16px;
  border-radius: var(--radius-md);
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-medium);
  height: 36px;
}
.button-secondary {
  background: var(--color-bg-surface);
  color: var(--color-text-primary);
  border: 1px solid var(--color-border);
  /* остальное как primary */
}
.button-ghost {
  background: transparent;
  color: var(--color-text-secondary);
  border: none;
}
```

**Запрещено:**
- ❌ Чёрные кнопки с белым текстом.
- ❌ Floating-кнопки в правом нижнем углу.
- ❌ Огромные кнопки высотой 48px+.
- ❌ Кнопки с цифрами в тексте (`Полный rewrite 14`). Счётчик = отдельный Badge рядом.

### 5.2. Карточки — граница вместо тени

```css
.card {
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-xl);    /* 28px */
  /* без box-shadow */
}
```

- Карточка занимает всю доступную ширину (max-width 1100px на странице).
- Внутренний padding 28px — не больше.
- Между карточками — отступ 20px.

### 5.3. Sidebar — см. SIDEBAR_SPEC.md

Активный пункт меню = **серый фон `--color-bg-muted`**, не цветной.

### 5.4. Иконки — Lucide stroke-width 1.75

- Библиотека: Lucide.
- Размер: 20px (inline), 16px (мелкий контекст).
- `stroke-width: 1.75` — тонкие линии.
- **Эмодзи в UI запрещены везде.**

### 5.5. Бейджи — 11px micro, pill radius

```css
.badge {
  padding: 2px 8px;
  border-radius: var(--radius-full);
  font-size: 11px;
  font-weight: var(--font-weight-medium);
  height: 20px;
}
.badge--neutral { background: var(--color-bg-muted); color: var(--color-text-secondary); }
.badge--success { background: var(--color-success-soft); color: var(--color-success); }
.badge--warning { background: var(--color-warning-soft); color: var(--color-warning); }
.badge--danger  { background: var(--color-danger-soft); color: var(--color-danger); }
.badge--accent  { background: var(--color-accent-soft); color: var(--color-accent-text); }
```

### 5.6. Markdown rendering

- Подключить markdown-парсер.
- `---` → `<hr style="border-top: 1px solid var(--color-border)">`.
- Литералный markdown в UI **запрещён**.

---

## 6. Чек-лист «выглядит ли как Claude»

После любого изменения проверь:

- [ ] Фон тёплый кремовый `#faf9f5`, не серый/синеватый.
- [ ] Текст почти чёрный `#141413`, не чистый `#000`.
- [ ] Акцент фиолетовый `#6366F1` (Вариант Б Pavel-а).
- [ ] Один шрифт в UI — Inter sans-serif. Никаких serif в заголовках, кнопках, меню.
- [ ] Заголовок страницы не больше 28px.
- [ ] Ни одного эмодзи в UI. Все на Lucide-иконки.
- [ ] Карточки имеют тонкую границу, тень либо отсутствует, либо еле заметна.
- [ ] Радиусы кнопок — 8px, не 16+.
- [ ] Высота кнопок — 36px, не 48+.
- [ ] Карточки занимают всю доступную ширину, не 60%.
- [ ] Нет чёрных капсул с белым текстом.
- [ ] Нет floating-кнопок в правом нижнем углу.
- [ ] Markdown-разделители `---` отрендерены как `<hr>`.
- [ ] Технические идентификаторы — мелким серым моноширинным.
- [ ] UPPERCASE только для маленьких eyebrow-labels (12px).
- [ ] **Активный пункт sidebar — серый, не цветной.**

---

## 7. Стоп-лист

- ❌ Serif-шрифты в UI.
- ❌ Эмодзи где-либо.
- ❌ Чёрные кнопки/капсулы.
- ❌ Floating action buttons.
- ❌ Градиенты на фонах.
- ❌ Цветные тени.
- ❌ Анимации длиннее 200ms.
- ❌ Заголовки больше 32px.
- ❌ Карточки уже 80% ширины контейнера.
- ❌ Литералный markdown в UI.
- ❌ Жёлтые/оранжевые/красные плашки с заливкой полной яркости (только -soft варианты).
- ❌ Цвета вне палитры.
- ❌ Декоративные иконки без функции.
- ❌ UPPERCASE на крупных заголовках.

**Этот документ — закон. При расхождении с любым другим документом проекта — побеждает этот.**
