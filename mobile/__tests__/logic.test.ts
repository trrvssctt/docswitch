import { convertedName, directionFor, kindFromMime } from '../src/utils/files';
import { formatShortDate, formatSize } from '../src/utils/format';
import { isFileError, precheck } from '../src/utils/precheck';
import { overallPercent, stepNumber } from '../src/utils/progress';

describe('precheck', () => {
  it('refuse plus de 50 Mo', () => {
    expect(precheck({ size: 63 * 1024 * 1024, passwordProtected: false })).toBe('FILE_TOO_LARGE');
  });
  it('refuse un PDF protégé', () => {
    expect(precheck({ size: 1000, passwordProtected: true })).toBe('PDF_PASSWORD_PROTECTED');
  });
  it('accepte un fichier normal', () => {
    expect(precheck({ size: 50 * 1024 * 1024, passwordProtected: false })).toBeNull();
  });
  it('distingue erreurs de fichier et erreurs réseau', () => {
    expect(isFileError('INVALID_FILE')).toBe(true);
    expect(isFileError('NETWORK')).toBe(false);
    expect(isFileError('SERVER')).toBe(false);
  });
});

describe('progression', () => {
  it('découpe la barre en trois étapes', () => {
    expect(overallPercent('upload', 0)).toBe(0);
    expect(overallPercent('upload', 1)).toBe(40);
    expect(overallPercent('download', 1)).toBe(100);
    expect(stepNumber('convert')).toBe(2);
  });
  it('n’atteint jamais la fin pendant la conversion', () => {
    expect(overallPercent('convert', 0, 0)).toBe(40);
    const late = overallPercent('convert', 0, 10 * 60_000);
    expect(late).toBeLessThan(88);
    expect(late).toBeGreaterThan(80);
  });
});

describe('fichiers', () => {
  it('renomme selon le format cible', () => {
    expect(convertedName('Rapport.pdf', 'docx')).toBe('Rapport.docx');
    expect(convertedName('sans extension', 'pdf')).toBe('sans extension.pdf');
  });
  it('reconnaît le type par MIME ou extension', () => {
    expect(kindFromMime('application/pdf')).toBe('pdf');
    expect(kindFromMime('application/octet-stream', 'Lettre.DOCX')).toBe('docx');
    expect(kindFromMime(null, 'image.png')).toBeNull();
    expect(directionFor('docx')).toBe('docx-to-pdf');
  });
});

describe('format', () => {
  it('affiche les tailles en français', () => {
    expect(formatSize(640 * 1024)).toBe('640 Ko');
    expect(formatSize(2.4 * 1024 * 1024)).toBe('2,4 Mo');
    expect(formatSize(63 * 1024 * 1024)).toBe('63 Mo');
  });
  it('affiche des dates relatives', () => {
    const now = new Date(2026, 10, 3, 18, 0).getTime();
    expect(formatShortDate(new Date(2026, 10, 3, 14, 32).getTime(), now)).toBe('14:32');
    expect(formatShortDate(new Date(2026, 10, 2, 9, 0).getTime(), now)).toBe('Hier');
    expect(formatShortDate(new Date(2026, 9, 30).getTime(), now)).toBe('30 oct.');
  });
});
