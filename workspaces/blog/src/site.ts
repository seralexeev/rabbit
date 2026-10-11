export const SITE = 'https://rabbit0.dev';

export const AUTHOR = {
    '@type': 'Person',
    name: 'Sergey Alekseev',
    url: 'https://www.linkedin.com/in/seralexeev',
    sameAs: ['https://github.com/seralexeev'],
};

export const REPO = 'https://github.com/seralexeev/rabbit';

export const DEFAULT_IMAGE = { src: '/media/og.jpg', width: 1200, height: 630 };

export type Lang = 'en' | 'ru';

export type Locale = {
    lang: Lang;
    og_locale: string;
    home: string;
    feed: string;
    post_path: (id: number) => string;
    name: string;
    title: string;
    description: string;
    image_alt: string;
    photo: string;
    video: string;
    play: string;
    all_posts: string;
    older: string;
    newer: string;
    note: string;
};

export const LOCALES: Record<Lang, Locale> = {
    en: {
        lang: 'en',
        og_locale: 'en_US',
        home: '/',
        feed: '/feed.xml',
        post_path: (id) => `/p/${id}/`,
        name: 'Robot Rabbit',
        title: 'Robot Rabbit · build log of an autonomous rover',
        description:
            'Build log of Rabbit, a small Ackermann rover built from scratch: Jetson and a ZED camera, NATS, autonomous navigation and exploration, custom PCBs and motor drives. Short posts with photos, plots and code.',
        image_alt: 'The Rabbit HUD: the rover in a voxel map of the flat',
        photo: 'photo',
        video: 'video',
        play: '▶ Play video',
        all_posts: 'all posts',
        older: 'older',
        newer: 'newer',
        note: 'translated from Russian',
    },
    ru: {
        lang: 'ru',
        og_locale: 'ru_RU',
        home: '/ru/',
        feed: '/ru/feed.xml',
        post_path: (id) => `/ru/p/${id}/`,
        name: 'Robot Rabbit',
        title: 'Robot Rabbit · дневник сборки автономного робота',
        description:
            'Дневник сборки Rabbit, маленького робота с рулевым управлением Аккермана: Jetson и камера ZED, NATS, автономная навигация и исследование квартиры, свои платы и приводы. Короткие посты с фото, графиками и кодом.',
        image_alt: 'HUD робота Rabbit: робот на воксельной карте квартиры',
        photo: 'фото',
        video: 'видео',
        play: '▶ Смотреть видео',
        all_posts: 'все посты',
        older: 'раньше',
        newer: 'позже',
        note: '',
    },
};

export const other_lang = (lang: Lang): Lang => (lang === 'en' ? 'ru' : 'en');

export const absolute = (href: string) => (href.startsWith('http') ? href : SITE + href);

export const iso_date = (date: string) => {
    const [day, month, year] = date.split('-');
    return `${year}-${month}-${day}`;
};

const sydney_offset = new Intl.DateTimeFormat('en-US', { timeZone: 'Australia/Sydney', timeZoneName: 'longOffset' });

export const published_at = (date: string) => {
    const iso = iso_date(date);
    const probe = new Date(`${iso}T12:00:00Z`);
    const zone = sydney_offset.formatToParts(probe).find((x) => x.type === 'timeZoneName')?.value ?? 'GMT+10:00';
    return `${iso}T00:00:00${zone.replace('GMT', '')}`;
};

export const esc = (value: string | number) =>
    String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const ENTITIES: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };

export const plain_text = (html: string) =>
    html
        .replace(/<\/(p|li|pre|blockquote|ul|ol|div|h\d|tr|td|th)>|<br\s*\/?>/g, ' ')
        .replace(/<[^>]+>/g, '')
        .replace(/&(#x?[0-9a-f]+|[a-z]+);/gi, (match, code: string) => {
            if (code.startsWith('#x') || code.startsWith('#X')) {
                return String.fromCodePoint(parseInt(code.slice(2), 16));
            }

            if (code.startsWith('#')) {
                return String.fromCodePoint(parseInt(code.slice(1), 10));
            }

            return ENTITIES[code.toLowerCase()] ?? match;
        })
        .replace(/\s+/g, ' ')
        .trim();

export const clip = (text: string, max: number) => {
    if (text.length <= max) {
        return text;
    }

    const cut = text.slice(0, max - 1);
    const space = cut.lastIndexOf(' ');
    return (space > max * 0.6 ? cut.slice(0, space) : cut).replace(/[\s,.;:!?(«"'-]+$/, '') + '…';
};

export const headline_of = (text: string) => {
    const sentence = text.match(/^.+?[.!?…](?=\s|$)/)?.[0] ?? text;
    return clip(sentence.replace(/[.:;]$/, ''), 60);
};
