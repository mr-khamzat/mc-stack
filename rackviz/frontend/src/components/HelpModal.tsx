import React from 'react'

interface Props {
  onClose: () => void
}

const Section: React.FC<{ title: string; icon: string; children: React.ReactNode }> = ({
  title, icon, children,
}) => (
  <div className="mb-8">
    <h2 className="text-base font-semibold text-white mb-3 flex items-center gap-2 border-b border-gray-700 pb-2">
      <span>{icon}</span> {title}
    </h2>
    <div className="text-gray-300 text-sm space-y-2 leading-relaxed">
      {children}
    </div>
  </div>
)

const Step: React.FC<{ n: number; children: React.ReactNode }> = ({ n, children }) => (
  <div className="flex gap-3">
    <span className="flex-shrink-0 w-5 h-5 rounded-full bg-gray-700 text-gray-400 text-xs
      flex items-center justify-center font-mono mt-0.5">
      {n}
    </span>
    <div>{children}</div>
  </div>
)

const Tag: React.FC<{ color?: string; children: React.ReactNode }> = ({
  color = 'bg-gray-700 text-gray-300', children,
}) => (
  <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${color}`}>
    {children}
  </span>
)

const Dot: React.FC<{ color: string; label: string }> = ({ color, label }) => (
  <div className="flex items-center gap-2">
    <span className="w-3 h-3 rounded" style={{ background: color }} />
    <span className="text-gray-400 text-xs">{label}</span>
  </div>
)

export const HelpModal: React.FC<Props> = ({ onClose }) => (
  <div
    className="fixed inset-0 z-50 flex items-start justify-center bg-black bg-opacity-75 overflow-y-auto py-8"
    onClick={e => e.target === e.currentTarget && onClose()}
  >
    <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-3xl mx-4 p-7">
      {/* Header */}
      <div className="flex items-center justify-between mb-7">
        <div>
          <h1 className="text-xl font-bold text-white">📖 Инструкция по работе с RackViz</h1>
          <p className="text-gray-500 text-sm mt-1">
            Визуализатор серверной стойки — как редактировать, добавлять оборудование и патчкорды
          </p>
        </div>
        <button
          onClick={onClose}
          className="text-gray-500 hover:text-white text-xl font-light leading-none ml-4"
        >
          ✕
        </button>
      </div>

      {/* ── 1. РЕЖИМЫ РАБОТЫ ─────────────────────────────────────────── */}
      <Section title="Режимы работы" icon="🎛">
        <p className="text-gray-400 mb-3">
          В верхней панели три кнопки — они переключают режим работы с стойкой:
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="bg-gray-800 rounded-lg p-3 border border-gray-700">
            <div className="text-white font-medium mb-1">👁 Просмотр</div>
            <div className="text-gray-400 text-xs">
              Только чтение. Кликни занятый порт — увидишь информацию о подключённом устройстве
              в боковой панели.
            </div>
          </div>
          <div className="bg-gray-800 rounded-lg p-3 border border-yellow-800">
            <div className="text-yellow-400 font-medium mb-1">✏ Редактировать</div>
            <div className="text-gray-400 text-xs">
              Назначение портов, перемещение оборудования, управление стойкой.
              Нужен вход как администратор.
            </div>
          </div>
          <div className="bg-gray-800 rounded-lg p-3 border border-blue-800">
            <div className="text-blue-400 font-medium mb-1">🔗 Патчкорды</div>
            <div className="text-gray-400 text-xs">
              Создание и удаление патчкордов между портами.
              Работает независимо от режима редактирования.
            </div>
          </div>
        </div>
      </Section>

      {/* ── 2. ВХОД ─────────────────────────────────────────────────── */}
      <Section title="Вход администратора" icon="🔑">
        <Step n={1}>
          Нажми кнопку <Tag>🔑 Войти</Tag> в правом верхнем углу.
        </Step>
        <Step n={2}>
          Введи логин и пароль администратора (по умолчанию: <code className="text-green-400">admin</code>).
        </Step>
        <Step n={3}>
          После входа появятся режимы <Tag color="bg-yellow-900 text-yellow-300">✏ Редактировать</Tag> и{' '}
          <Tag color="bg-blue-900 text-blue-300">🔗 Патчкорды</Tag>.
        </Step>
        <p className="text-gray-500 text-xs mt-2">
          Сессия сохраняется на 30 дней. Повторный вход не нужен.
          Авторизация через RackViz также открывает доступ к карте сети (NetMap).
        </p>
      </Section>

      {/* ── 3. НАЗНАЧЕНИЕ ПОРТОВ ─────────────────────────────────────── */}
      <Section title="Как назначить порт" icon="🔌">
        <p className="text-gray-400 mb-3">
          Каждый порт на устройстве можно связать с реальным оборудованием.
          Поддерживается три типа назначения:
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
          <div className="bg-gray-800 rounded-lg p-3">
            <div className="font-medium text-white mb-1">🖥 MeshCentral агент</div>
            <div className="text-gray-400 text-xs">
              Выбираешь ПК из списка онлайн-агентов. Статус порта обновляется в реальном времени —
              зелёный если ПК онлайн, красный если офлайн.
            </div>
          </div>
          <div className="bg-gray-800 rounded-lg p-3">
            <div className="font-medium text-white mb-1">✍ Ручное</div>
            <div className="text-gray-400 text-xs">
              Любое оборудование без агента: коммутатор, камера, IP-телефон, принтер.
              Вводишь название, IP, MAC, описание.
            </div>
          </div>
          <div className="bg-gray-800 rounded-lg p-3">
            <div className="font-medium text-white mb-1">📶 WiFi-сосед</div>
            <div className="text-gray-400 text-xs">
              Устройство обнаружено через Keenetic зонд.
              Выбираешь из списка соседей сети.
            </div>
          </div>
        </div>

        <p className="font-medium text-gray-300 mb-2">Шаги:</p>
        <Step n={1}>Переключись в <Tag color="bg-yellow-900 text-yellow-300">✏ Редактировать</Tag></Step>
        <Step n={2}>Кликни на <b className="text-white">любой порт</b> на любом устройстве (рамка порта станет заметнее в режиме редактирования)</Step>
        <Step n={3}>Откроется диалог «Назначить порт». Выбери тип: MeshCentral / Ручное / WiFi-сосед</Step>
        <Step n={4}>Заполни поля и нажми <Tag color="bg-blue-800 text-blue-200">Сохранить</Tag></Step>
        <Step n={5}>Чтобы <b className="text-white">освободить порт</b> — открой диалог и нажми <Tag color="bg-red-900 text-red-300">Освободить</Tag></Step>
      </Section>

      {/* ── 4. ЦВЕТА ПОРТОВ ─────────────────────────────────────────── */}
      <Section title="Что означают цвета портов" icon="🎨">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          <Dot color="#202020" label="Тёмный — порт свободен" />
          <Dot color="#14532d" label="Зелёный — MC агент онлайн" />
          <Dot color="#7f1d1d" label="Красный — MC агент офлайн" />
          <Dot color="#1e1b4b" label="Индиго — ручное устройство" />
          <Dot color="#78350f" label="Янтарный — Uplink порт" />
        </div>
        <p className="text-gray-500 text-xs mt-3">
          LED-точка в правом верхнем углу порта дублирует статус.
          Наведи мышь на порт — увидишь подсказку с названием подключённого устройства.
        </p>
      </Section>

      {/* ── 5. ПАТЧКОРДЫ ─────────────────────────────────────────────── */}
      <Section title="Патчкорды — создание и удаление" icon="🔗">
        <p className="text-gray-400 mb-3">
          Патчкорды — физические кабели между портами разных устройств.
          Отображаются как цветные дуги через правый кабельный канал.
        </p>

        <p className="font-medium text-gray-300 mb-2">Создать патчкорд:</p>
        <Step n={1}>
          Нажми <Tag color="bg-blue-900 text-blue-300">🔗 Патчкорды</Tag> в верхней панели
        </Step>
        <Step n={2}>
          Выбери <b className="text-white">цвет кабеля</b> из палитры (жёлтый, синий, красный и т.д.)
        </Step>
        <Step n={3}>
          Кликни на <b className="text-white">первый порт</b> (Порт A) — внизу появится синяя полоска подтверждения
        </Step>
        <Step n={4}>
          Кликни на <b className="text-white">второй порт</b> (Порт B) — патчкорд создастся мгновенно
        </Step>

        <p className="font-medium text-gray-300 mb-2 mt-4">Удалить патчкорд:</p>
        <Step n={1}>Находясь в режиме <Tag color="bg-blue-900 text-blue-300">🔗 Патчкорды</Tag></Step>
        <Step n={2}>Кликни прямо на <b className="text-white">линию кабеля</b> в SVG-схеме</Step>
        <Step n={3}>Появится диалог подтверждения → нажми <Tag color="bg-red-900 text-red-300">Удалить</Tag></Step>

        <p className="text-gray-500 text-xs mt-3">
          Совет: используй цвет кабеля для обозначения назначения — синий = данные, красный = управление,
          жёлтый = интернет, зелёный = DMZ и т.д.
        </p>
      </Section>

      {/* ── 6. ПЕРЕМЕЩЕНИЕ ОБОРУДОВАНИЯ ─────────────────────────────── */}
      <Section title="Перемещение оборудования в стойке" icon="↕">
        <p className="text-gray-400 mb-3">
          В режиме <Tag color="bg-yellow-900 text-yellow-300">✏ Редактировать</Tag> доступны два способа:
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="bg-gray-800 rounded-lg p-3">
            <div className="font-medium text-white mb-1">▲▼ Кнопки</div>
            <div className="text-gray-400 text-xs">
              Кнопки ▲ и ▼ появляются в правом углу каждого устройства.
              Меняет местами с соседним устройством выше/ниже.
              Удобно для точного позиционирования.
            </div>
          </div>
          <div className="bg-gray-800 rounded-lg p-3">
            <div className="font-medium text-white mb-1">⠿ Перетаскивание</div>
            <div className="text-gray-400 text-xs">
              Нажми и удерживай ручку ⠿ (маленький значок в правой части панели),
              затем тяни вверх или вниз.
              Синяя рамка показывает целевую позицию.
              Отпусти для установки.
            </div>
          </div>
        </div>
        <p className="text-gray-500 text-xs mt-3">
          Если позиция занята другим устройством, перемещение будет отменено.
          Для 2U серверов позиция считается по верхнему юниту.
        </p>
      </Section>

      {/* ── 7. УПРАВЛЕНИЕ СТОЙКОЙ ───────────────────────────────────── */}
      <Section title="Управление составом стойки" icon="⚙">
        <p className="text-gray-400 mb-3">
          Кнопка <Tag color="bg-gray-700 text-gray-300">⚙ Стойка</Tag> (появляется в режиме редактирования)
          открывает менеджер оборудования.
        </p>
        <p className="font-medium text-gray-300 mb-2">Добавить новое устройство:</p>
        <Step n={1}>Открой менеджер стойки → вкладка «Добавить»</Step>
        <Step n={2}>Введи название (напр. <code className="text-green-400">SW-04</code>)</Step>
        <Step n={3}>Выбери тип устройства (Коммутатор / Патч-панель / Сервер / и т.д.)</Step>
        <Step n={4}>Укажи позицию в юнитах (U), количество портов, высоту (1U / 2U / …)</Step>
        <Step n={5}>Нажми <Tag color="bg-green-900 text-green-300">Добавить</Tag></Step>

        <p className="font-medium text-gray-300 mb-2 mt-4">Удалить устройство:</p>
        <p className="text-gray-400">
          В менеджере стойки найди устройство в списке →{' '}
          нажми <Tag color="bg-red-900 text-red-300">🗑 Удалить</Tag>.
          Все порты устройства будут освобождены, все патчкорды — удалены.
        </p>

        <div className="bg-gray-800 rounded-lg p-3 mt-3 border border-gray-700">
          <p className="text-gray-300 text-xs font-medium mb-1">📋 Типы устройств:</p>
          <div className="grid grid-cols-2 gap-1 text-xs text-gray-400">
            <span><span className="text-amber-600">■</span> Патч-панель — PP</span>
            <span><span className="text-blue-600">■</span> Коммутатор — SW</span>
            <span><span className="text-purple-600">■</span> Хаб — HUB</span>
            <span><span className="text-green-600">■</span> Роутер — RTR</span>
            <span><span className="text-red-600">■</span> Сервер — SRV</span>
            <span><span className="text-orange-600">■</span> PoE Switch — PoE</span>
            <span><span className="text-cyan-600">■</span> ISP Switch — ISP</span>
            <span><span className="text-lime-600">■</span> Auth Router — AUTH</span>
          </div>
        </div>
      </Section>

      {/* ── 8. ПРОСМОТР УСТРОЙСТВА ───────────────────────────────────── */}
      <Section title="Просмотр информации об устройстве" icon="ℹ">
        <Step n={1}>
          В режиме <Tag>👁 Просмотр</Tag> кликни на <b className="text-white">занятый порт</b>
          (не тёмный — с цветным безелем)
        </Step>
        <Step n={2}>
          Откроется боковая панель справа с подробной информацией:
          имя устройства, IP, MAC, статус онлайн/офлайн, описание
        </Step>
        <Step n={3}>
          Для MC-агентов доступна кнопка <Tag color="bg-blue-900 text-blue-300">Открыть в MeshCentral</Tag>
        </Step>
      </Section>

      {/* ── 9. БЫСТРЫЕ СОВЕТЫ ─────────────────────────────────────────── */}
      <Section title="Быстрые советы" icon="💡">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs text-gray-400">
          <div className="flex gap-2">
            <span className="text-blue-400 flex-shrink-0">→</span>
            Кнопка <b className="text-white">🗺 NetMap</b> открывает интерактивную карту сети
          </div>
          <div className="flex gap-2">
            <span className="text-blue-400 flex-shrink-0">→</span>
            Наведи мышь на порт — всплывает подсказка с именем устройства
          </div>
          <div className="flex gap-2">
            <span className="text-blue-400 flex-shrink-0">→</span>
            Портовый счётчик обновляется каждые 60 сек (MC агенты)
          </div>
          <div className="flex gap-2">
            <span className="text-blue-400 flex-shrink-0">→</span>
            Группы по 6 портов в патч-панелях чередуют фон для навигации
          </div>
          <div className="flex gap-2">
            <span className="text-blue-400 flex-shrink-0">→</span>
            Цвет левой полосы устройства = тип оборудования
          </div>
          <div className="flex gap-2">
            <span className="text-blue-400 flex-shrink-0">→</span>
            LED над портами коммутатора: зелёный = онлайн, красный = офлайн
          </div>
        </div>
      </Section>

      <div className="text-center text-gray-600 text-xs mt-6 pt-4 border-t border-gray-800">
        RackViz — визуализатор серверной стойки с интеграцией MeshCentral
      </div>
    </div>
  </div>
)
