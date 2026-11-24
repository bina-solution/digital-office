"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.HelloWorld = void 0;
class HelloWorld {
    constructor() {
        this.description = {
            displayName: 'Hello World8',
            name: 'helloWorld',
            group: ['transform'],
            version: 1,
            description: 'Returns a greeting or echoes input text',
            defaults: {
                name: 'Hello World66',
            },
            inputs: ['main'],
            outputs: ['main'],
            properties: [
                {
                    displayName: 'Text',
                    name: 'text',
                    type: 'string',
                    default: 'World',
                    placeholder: 'World',
                    required: true,
                    description: 'Text to include in greeting.55'
                },
                {
                    displayName: 'Uppercase',
                    name: 'uppercase',
                    type: 'boolean',
                    default: false,
                    description: 'Whether to uppercase the greeting.'
                }
            ]
        };
    }
    async execute() {
        const items = this.getInputData();
        const returnData = [];
        for (let i = 0; i < items.length; i++) {
            const text = this.getNodeParameter('text', i);
            const uppercase = this.getNodeParameter('uppercase', i);
            let greeting = `Hello ${text}`;
            if (uppercase)
                greeting = greeting.toUpperCase();
            returnData.push({ json: { greeting, original: text, uppercase } });
        }
        // Return as array of arrays per latest NodeOutput type expectation
        return [returnData];
    }
}
exports.HelloWorld = HelloWorld;
