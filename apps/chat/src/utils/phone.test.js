const { normalizePhone } = require('./phone');

// Using default country code from env or default 972.
process.env.DEFAULT_COUNTRY_CODE = process.env.DEFAULT_COUNTRY_CODE || '972';

describe('normalizePhone', () => {
  it('keeps full international with +', () => {
    expect(normalizePhone('050-000-0005')).toBe('050-000-0005');
  });

  it('converts 00 prefix to international', () => {
    expect(normalizePhone('00972548284680')).toBe('050-000-0005');
  });

  it('prepends default CC when starts with 0', () => {
    expect(normalizePhone('050-000-0005')).toBe('050-000-0005');
  });

  it('prepends default CC for local length 9-10', () => {
    expect(normalizePhone('548284680')).toBe('050-000-0005');
  });

  it('leaves already international without + as-is', () => {
    expect(normalizePhone('050-000-0005')).toBe('050-000-0005');
  });

  it('strips non-digits except leading +', () => {
    expect(normalizePhone(' (054) 828-4680 ')).toBe('050-000-0005');
  });
});
