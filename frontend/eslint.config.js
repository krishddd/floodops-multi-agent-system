import js from '@eslint/js';
import globals from 'globals';

export default [
    js.configs.recommended,
    {
        files: ['src/**/*.js'],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: 'module',
            globals: { ...globals.browser, google: 'readonly' },
        },
        rules: {
            'no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
            'no-console': 'off',
            'no-empty': ['error', { allowEmptyCatch: true }],
        },
    },
    {
        files: ['src/**/__tests__/**/*.js'],
        languageOptions: { globals: { ...globals.node } },
    },
];
