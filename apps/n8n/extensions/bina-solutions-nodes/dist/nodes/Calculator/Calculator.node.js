"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.Calculator = void 0;
class Calculator {
    constructor() {
        this.description = {
            displayName: 'Calculator',
            name: 'calculator',
            group: ['transform'],
            version: 1,
            description: 'Basic Calculator',
            defaults: {
                name: 'Calculator',
            },
            inputs: ['main'],
            outputs: ['main'],
            properties: [
                {
                    displayName: 'Operation',
                    name: 'operation',
                    type: 'options',
                    options: [
                        {
                            name: 'Add',
                            value: 'add',
                        },
                        {
                            name: 'Subtract',
                            value: 'subtract',
                        },
                        {
                            name: 'Multiply',
                            value: 'multiply',
                        },
                        {
                            name: 'Divide',
                            value: 'divide',
                        },
                    ],
                    default: 'add',
                    description: 'The operation to perform.',
                },
                {
                    displayName: 'Number 1',
                    name: 'number1',
                    type: 'number',
                    default: 0,
                    required: true,
                    description: 'The first number.',
                },
                {
                    displayName: 'Number 2',
                    name: 'number2',
                    type: 'number',
                    default: 0,
                    required: true,
                    description: 'The second number.',
                },
            ],
        };
    }
    async execute() {
        const items = this.getInputData();
        const returnData = [];
        for (let i = 0; i < items.length; i++) {
            const operation = this.getNodeParameter('operation', i);
            const number1 = this.getNodeParameter('number1', i);
            const number2 = this.getNodeParameter('number2', i);
            let result;
            switch (operation) {
                case 'add':
                    result = number1 + number2;
                    break;
                case 'subtract':
                    result = number1 - number2;
                    break;
                case 'multiply':
                    result = number1 * number2;
                    break;
                case 'divide':
                    result = number1 / number2;
                    break;
                default:
                    result = 0;
            }
            returnData.push({ json: { result, operation, number1, number2 } });
        }
        return [returnData];
    }
}
exports.Calculator = Calculator;
