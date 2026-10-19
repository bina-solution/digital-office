/*!
 * Built by Revolist OU ❤️
 */
class ThemeCompact {
    constructor() {
        this.defaultRowSize = 32;
    }
}

class ThemeDefault {
    constructor() {
        this.defaultRowSize = 27;
    }
}

class ThemeMaterial {
    constructor() {
        this.defaultRowSize = 42;
    }
}

const DEFAULT_THEME = 'default';
const allowedThemes = [
    DEFAULT_THEME,
    'material',
    'compact',
    'darkMaterial',
    'darkCompact',
];
class ThemeService {
    get theme() {
        return this.currentTheme;
    }
    get rowSize() {
        return this.customRowSize || this.currentTheme.defaultRowSize;
    }
    set rowSize(size) {
        this.customRowSize = size;
    }
    constructor(cfg) {
        this.customRowSize = 0;
        this.customRowSize = cfg.rowSize;
        this.register('default');
    }
    register(theme) {
        const parsedTheme = getTheme(theme);
        switch (parsedTheme) {
            case 'material':
            case 'darkMaterial':
                this.currentTheme = new ThemeMaterial();
                break;
            case 'compact':
            case 'darkCompact':
                this.currentTheme = new ThemeCompact();
                break;
            default:
                this.currentTheme = new ThemeDefault();
                break;
        }
    }
}
function getTheme(theme) {
    if (theme && allowedThemes.indexOf(theme) > -1) {
        return theme;
    }
    return DEFAULT_THEME;
}

export { ThemeService as T, getTheme as g };
