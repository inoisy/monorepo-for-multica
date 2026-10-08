import React from 'react';
import {C, FONT} from './brand';
import type {FilmProps} from './data';
import {STOPS} from './geometry';
import {Check, DocGlyph} from './icons';
import {cardTime} from './motion';
import {easeInOut, easeOut, ip, mix, pop} from './time';

const Shell: React.FC<{k: number; title: string; sub: string; children: React.ReactNode; badge?: React.ReactNode}> = ({k, title, sub, children, badge}) => (
  <div
    style={{
      width: '100%',
      height: '100%',
      background: '#fff',
      borderRadius: 34,
      boxShadow: '0 30px 80px rgba(27,19,64,0.35)',
      overflow: 'hidden',
      fontFamily: FONT,
      color: C.ink,
      display: 'flex',
      flexDirection: 'column',
    }}
  >
    <div style={{display: 'flex', alignItems: 'center', gap: 18, padding: '26px 36px', borderBottom: '2px solid #EEEBF7'}}>
      <div style={{width: 56, height: 56, borderRadius: 16, background: STOPS[k].color, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
        <DocGlyph kind={k} color="#fff" size={34} />
      </div>
      <div style={{flex: 1}}>
        <div style={{fontSize: 30, fontWeight: 750}}>{title}</div>
        <div style={{fontSize: 20, color: C.muted, marginTop: 2}}>{sub}</div>
      </div>
      {badge}
    </div>
    <div style={{flex: 1, position: 'relative', padding: '26px 36px'}}>{children}</div>
  </div>
);

const AgentBadge: React.FC<{t: number; at: number; text: string}> = ({t, at, text}) => {
  const s = pop(t, at, 12);
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        background: C.purple,
        color: '#fff',
        borderRadius: 30,
        padding: '10px 20px',
        fontSize: 21,
        fontWeight: 650,
        transform: `scale(${s})`,
        opacity: Math.min(1, s * 2),
      }}
    >
      <Check size={22} color="#fff" stroke={3.5} />
      {text}
    </div>
  );
};

// 1. A memo the agent writes itself, then it gets approved.
const MEMO =
  'Прошу согласовать командировку инженера отдела внедрения в Казань с 14 по 16 октября для запуска проекта у заказчика. Билеты и гостиница подобраны, смета приложена.';

const Memo: React.FC<{t: number}> = ({t}) => {
  const chars = Math.floor(ip(t, [30, 105], [0, MEMO.length]));
  const stamp = pop(t, 112, 9);
  const caret = chars < MEMO.length && Math.floor(t / 6) % 2 === 0;
  return (
    <Shell k={0} title="Служебная записка № 214" sub="Административный отдел · 08.10.2026" badge={<AgentBadge t={t} at={120} text="Агент · 38 сек" />}>
      {[
        ['Кому', 'Генеральному директору ООО «Лоция»'],
        ['От', 'Административный отдел'],
        ['Тема', 'Командировка, Казань'],
      ].map(([a, b], i) => (
        <div key={a} style={{display: 'flex', gap: 16, fontSize: 24, marginBottom: 8, opacity: ip(t, [8 + i * 6, 18 + i * 6], [0, 1])}}>
          <span style={{width: 90, color: C.muted}}>{a}</span>
          <span style={{fontWeight: 600}}>{b}</span>
        </div>
      ))}
      <div style={{marginTop: 22, fontSize: 27, lineHeight: 1.5, minHeight: 170}}>
        {MEMO.slice(0, chars)}
        {caret && <span style={{display: 'inline-block', width: 3, height: 30, background: C.purple, verticalAlign: 'middle', marginLeft: 2}} />}
      </div>
      <div
        style={{
          position: 'absolute',
          right: 60,
          bottom: 34,
          border: `6px solid ${C.purple}`,
          color: C.purple,
          borderRadius: 14,
          padding: '8px 26px',
          fontSize: 40,
          fontWeight: 850,
          letterSpacing: 4,
          transform: `rotate(-10deg) scale(${mix(2.6, 1, stamp)})`,
          opacity: stamp > 0.02 ? Math.min(1, stamp * 1.5) : 0,
        }}
      >
        СОГЛАСОВАНО
      </div>
    </Shell>
  );
};

// 2. A task in Sphere moves itself to "done".
const COLS = ['Новые', 'В работе', 'Готово'];
const Task: React.FC<{title: string; tag?: string; color?: string; style?: React.CSSProperties; children?: React.ReactNode}> = ({title, tag, color = C.muted, style, children}) => (
  <div
    style={{
      background: '#fff',
      border: '2px solid #E6E2F3',
      borderRadius: 16,
      padding: '14px 16px',
      fontSize: 21,
      fontWeight: 600,
      boxSizing: 'border-box',
      width: 300,
      ...style,
    }}
  >
    {title}
    {tag && <div style={{marginTop: 8, fontSize: 16, fontWeight: 600, color}}>{tag}</div>}
    {children}
  </div>
);

const Sphere: React.FC<{t: number}> = ({t}) => {
  const move = ip(t, [32, 72], [0, 1], easeInOut);
  const lift = Math.sin(move * Math.PI);
  const done = t > 74;
  const progress = ip(t, [82, 140], [0, 100]);
  const comment = pop(t, 96, 13);
  const colX = (c: number) => c * 340;
  return (
    <Shell k={1} title="Сфера · задачи отдела" sub="sphere.loodsen.ru · спринт 41" badge={<AgentBadge t={t} at={78} text="Агент закрыл задачу" />}>
      <div style={{position: 'relative', height: '100%'}}>
        {COLS.map((c, i) => (
          <div key={c} style={{position: 'absolute', left: colX(i), top: 0, width: 320, height: 430, background: '#F5F3FB', borderRadius: 20}}>
            <div style={{padding: '14px 18px', fontSize: 20, fontWeight: 700, color: C.muted}}>
              {c}
              <span style={{marginLeft: 10, color: C.purple}}>{i === 0 ? 2 : i === 1 ? (done ? 1 : 2) : done ? 3 : 2}</span>
            </div>
          </div>
        ))}
        <Task title="Заказать канцтовары" tag="до пятницы" style={{position: 'absolute', left: 10, top: 56}} />
        <Task title="Пропуск для гостя" tag="завтра, 10:00" style={{position: 'absolute', left: 10, top: 160}} />
        <Task title="График отпусков, IV кв." tag={`собрано ${Math.round(progress)}%`} color={C.purple} style={{position: 'absolute', left: colX(1) + 10, top: mix(160, 56, ip(t, [40, 70], [0, 1], easeInOut))}}>
          <div style={{marginTop: 8, height: 8, background: '#EEEBF7', borderRadius: 4}}>
            <div style={{width: `${progress}%`, height: 8, background: C.purple, borderRadius: 4}} />
          </div>
        </Task>
        <Task title="Договор аренды" tag="подписан" color={C.teal} style={{position: 'absolute', left: colX(2) + 10, top: mix(56, 160, move)}} />
        <Task title="Счёт № 1189" tag="оплачен" color={C.teal} style={{position: 'absolute', left: colX(2) + 10, top: mix(160, 264, move)}} />
        <Task
          title="Закрыть акты за сентябрь"
          tag={done ? 'готово · 12 из 12' : 'в работе'}
          color={done ? C.teal : C.orange}
          style={{
            position: 'absolute',
            left: mix(colX(1) + 10, colX(2) + 10, move),
            top: mix(264, 56, move) - lift * 40,
            transform: `rotate(${lift * 4}deg) scale(${1 + lift * 0.06})`,
            boxShadow: `0 ${10 + lift * 30}px ${20 + lift * 40}px rgba(27,19,64,${0.12 + lift * 0.2})`,
            borderColor: done ? C.teal : C.purple,
            zIndex: 2,
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: 640,
            top: 400,
            width: 380,
            background: C.ink,
            color: '#fff',
            borderRadius: 18,
            padding: '14px 18px',
            fontSize: 19,
            lineHeight: 1.4,
            transform: `translateY(${(1 - comment) * 30}px)`,
            opacity: comment,
            zIndex: 3,
          }}
        >
          <b style={{color: C.purpleSoft}}>Агент:</b> акты сверены с 1С и отправлены в бухгалтерию
        </div>
      </div>
    </Shell>
  );
};

// 3. A report whose chart is drawn from the viewer's own numbers.
const MONTHS = ['Май', 'Июнь', 'Июль', 'Авг', 'Сент', 'Окт'];
const Report: React.FC<{t: number; props: FilmProps}> = ({t, props}) => {
  const max = Math.max(...props.monthly);
  const first = props.monthly[0];
  const last = props.monthly[props.monthly.length - 1];
  const drop = Math.round(((first - last) / first) * 100);
  const kpi = ip(t, [70, 120], [0, drop], easeOut);
  return (
    <Shell k={2} title="Отчёт: ручная работа с документами" sub={`${props.dept} · часов в месяц`} badge={<AgentBadge t={t} at={110} text="Собран из Сферы и 1С" />}>
      <div style={{display: 'flex', height: '100%', gap: 40}}>
        <div style={{flex: 1, position: 'relative', display: 'flex', alignItems: 'flex-end', gap: 22, paddingBottom: 40}}>
          {props.monthly.map((v, i) => {
            const g = ip(t, [26 + i * 8, 56 + i * 8], [0, 1], easeOut);
            const h = (v / max) * 330 * g;
            const after = i >= 3;
            return (
              <div key={i} style={{flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-end', height: '100%'}}>
                <div style={{fontSize: 22, fontWeight: 700, marginBottom: 6, opacity: g}}>{Math.round(v * g)}</div>
                <div style={{width: '100%', height: h, borderRadius: '12px 12px 4px 4px', background: after ? C.purple : '#CFC6EA'}} />
                <div style={{position: 'absolute', bottom: 0, fontSize: 19, color: C.muted, transform: `translateX(0)`}}>{MONTHS[i]}</div>
              </div>
            );
          })}
          <div
            style={{
              position: 'absolute',
              left: '50%',
              top: 0,
              bottom: 40,
              borderLeft: `3px dashed ${C.orange}`,
              opacity: ip(t, [60, 75], [0, 1]),
            }}
          >
            <div style={{position: 'absolute', left: 10, top: 0, background: C.orange, color: '#fff', fontSize: 18, fontWeight: 700, padding: '4px 12px', borderRadius: 12, whiteSpace: 'nowrap'}}>
              подключили агентов
            </div>
          </div>
        </div>
        <div style={{width: 290, display: 'flex', flexDirection: 'column', justifyContent: 'center'}}>
          <div style={{fontSize: 100, fontWeight: 850, color: C.purple, lineHeight: 1, whiteSpace: 'nowrap'}}>−{Math.round(kpi)}%</div>
          <div style={{fontSize: 24, marginTop: 12, lineHeight: 1.35}}>ручной работы с документами</div>
          <div style={{fontSize: 22, marginTop: 18, color: C.muted, opacity: ip(t, [100, 115], [0, 1])}}>
            {props.hoursSaved} ч в месяц вернулись команде
          </div>
        </div>
      </div>
    </Shell>
  );
};

// 4. The agent reports back in the corporate messenger.
const Bubble: React.FC<{me?: boolean; t: number; at: number; children: React.ReactNode}> = ({me, t, at, children}) => {
  const s = pop(t, at, 13);
  return (
    <div
      style={{
        alignSelf: me ? 'flex-end' : 'flex-start',
        maxWidth: 560,
        background: me ? '#EEEBF7' : C.purple,
        color: me ? C.ink : '#fff',
        borderRadius: me ? '22px 22px 6px 22px' : '22px 22px 22px 6px',
        padding: '14px 20px',
        fontSize: 22,
        lineHeight: 1.45,
        transform: `translateY(${(1 - s) * 24}px) scale(${mix(0.9, 1, s)})`,
        transformOrigin: me ? '100% 100%' : '0 100%',
        opacity: Math.min(1, s * 1.6),
      }}
    >
      {children}
    </div>
  );
};

const LooC: React.FC<{t: number; props: FilmProps}> = ({t, props}) => {
  const typing = t > 28 && t < 52;
  return (
    <Shell k={3} title="LooC · Агент администрирования" sub="в сети" badge={<AgentBadge t={t} at={118} text="Отчитался сам" />}>
      <div style={{display: 'flex', height: '100%', gap: 26}}>
        <div style={{width: 230, display: 'flex', flexDirection: 'column', gap: 10}}>
          {['Агент администрирования', 'Бухгалтерия', 'Офис', 'Новости Лоции'].map((c, i) => (
            <div key={c} style={{padding: '12px 14px', borderRadius: 14, background: i === 0 ? '#EEEBF7' : 'transparent', fontSize: 18, fontWeight: i === 0 ? 700 : 500, color: i === 0 ? C.purple : C.muted}}>
              {c}
            </div>
          ))}
        </div>
        <div style={{flex: 1, display: 'flex', flexDirection: 'column', gap: 14, justifyContent: 'flex-end', paddingBottom: 6}}>
          <Bubble me t={t} at={8}>
            Что по документам на этой неделе?
          </Bubble>
          {typing && (
            <div style={{alignSelf: 'flex-start', background: C.purple, borderRadius: 22, padding: '16px 22px', display: 'flex', gap: 8}}>
              {[0, 1, 2].map((i) => (
                <div key={i} style={{width: 12, height: 12, borderRadius: 6, background: '#fff', opacity: 0.4 + 0.6 * Math.abs(Math.sin(t * 0.25 - i))}} />
              ))}
            </div>
          )}
          {t >= 52 && (
            <Bubble t={t} at={52}>
              {props.name}, всё готово:
              <br />— служебка согласована
              <br />— акты в Сфере закрыты
              <br />— отчёт за сентябрь во вложении
            </Bubble>
          )}
          {t >= 84 && (
            <Bubble t={t} at={84}>
              <div style={{display: 'flex', alignItems: 'center', gap: 12}}>
                <div style={{width: 44, height: 44, borderRadius: 10, background: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
                  <DocGlyph kind={0} color={C.purple} size={28} />
                </div>
                <div>
                  <div style={{fontWeight: 700}}>Отчёт_сентябрь.pdf</div>
                  <div style={{fontSize: 17, opacity: 0.8}}>240 КБ</div>
                </div>
              </div>
            </Bubble>
          )}
        </div>
      </div>
    </Shell>
  );
};

export const StopCard: React.FC<{k: number; f: number; props: FilmProps}> = ({k, f, props}) => {
  const t = cardTime(f, k);
  if (k === 0) return <Memo t={t} />;
  if (k === 1) return <Sphere t={t} />;
  if (k === 2) return <Report t={t} props={props} />;
  return <LooC t={t} props={props} />;
};
