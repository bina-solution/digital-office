import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : whatsapp api
// Nodes   : 14  |  Connections: 21
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenCalled                         executeWorkflowTrigger
// OpSwitch                           switch
// Done                               noOp
// UnknownOp                          code
// WSend                              httpRequest                [creds] [retry]
// WSenddocument                      httpRequest                [creds] [retry]
// WSendimage                         httpRequest                [creds] [retry]
// WState                             httpRequest                [creds] [retry]
// WQr                                httpRequest                [creds] [retry]
// WDisconnect                        httpRequest                [creds] [retry]
// WBroadcast                         httpRequest                [creds] [retry]
// WCreategroup                       httpRequest                [creds] [retry]
// WGroupparticipants                 httpRequest                [creds] [retry]
// ShapeReply                         code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → OpSwitch
//      → WSend
//        → ShapeReply
//          → Done
//     .out(1) → WSenddocument
//        → ShapeReply (↩ loop)
//     .out(2) → WSendimage
//        → ShapeReply (↩ loop)
//     .out(3) → WState
//        → ShapeReply (↩ loop)
//     .out(4) → WQr
//        → ShapeReply (↩ loop)
//     .out(5) → WDisconnect
//        → ShapeReply (↩ loop)
//     .out(6) → WBroadcast
//        → ShapeReply (↩ loop)
//     .out(7) → WCreategroup
//        → ShapeReply (↩ loop)
//     .out(8) → WGroupparticipants
//        → ShapeReply (↩ loop)
//     .out(9) → UnknownOp
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: "The chat capability's callable surface. Called as a sub-workflow with {op, params}; every op maps to a route chat already serves.",
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"Op Switch","type":"main","index":0}]]},"Op Switch":{"main":[[{"node":"w:send","type":"main","index":0}],[{"node":"w:sendDocument","type":"main","index":0}],[{"node":"w:sendImage","type":"main","index":0}],[{"node":"w:state","type":"main","index":0}],[{"node":"w:qr","type":"main","index":0}],[{"node":"w:disconnect","type":"main","index":0}],[{"node":"w:broadcast","type":"main","index":0}],[{"node":"w:createGroup","type":"main","index":0}],[{"node":"w:groupParticipants","type":"main","index":0}],[{"node":"Unknown op","type":"main","index":0}]]},"w:send":{"main":[[{"node":"Shape reply","type":"main","index":0}]]},"w:sendDocument":{"main":[[{"node":"Shape reply","type":"main","index":0}]]},"w:sendImage":{"main":[[{"node":"Shape reply","type":"main","index":0}]]},"w:state":{"main":[[{"node":"Shape reply","type":"main","index":0}]]},"w:qr":{"main":[[{"node":"Shape reply","type":"main","index":0}]]},"w:disconnect":{"main":[[{"node":"Shape reply","type":"main","index":0}]]},"w:broadcast":{"main":[[{"node":"Shape reply","type":"main","index":0}]]},"w:createGroup":{"main":[[{"node":"Shape reply","type":"main","index":0}]]},"w:groupParticipants":{"main":[[{"node":"Shape reply","type":"main","index":0}]]},"Shape reply":{"main":[[{"node":"Done","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"3f73a1b7-a0d8-5181-9002-53c24aec83c3","name":"app:chat"},{"updatedAt":"2026-07-30T23:40:32.793Z","createdAt":"2026-07-30T23:40:32.793Z","id":"1cf85ce8-f830-4eee-b74a-07eb4be0e634","name":"api"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"7aee870d-aa7f-4f73-8f31-b134aabee59b","name":"chat-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"51804d94-1071-4213-980b-a06491a07895","name":"role:api"},{"updatedAt":"2026-07-30T23:40:32.793Z","createdAt":"2026-07-30T23:40:32.793Z","id":"c6a259fc-e9ce-443f-8169-e5a05a019c4b","name":"whatsapp"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {"templateCredsSetupCompleted":true},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:40:40.836Z","createdAt":"2026-07-30T23:40:40.836Z","role":"workflow:owner","workflowId":"whatsappApi01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'whatsappApi01',
    name: 'whatsapp api',
    active: true,
    description:
        "The chat capability's callable surface. Called as a sub-workflow with {op, params}; every op maps to a route chat already serves.",
    isArchived: false,
    tags: ['app:chat', 'api', 'chat-app', 'role:api', 'whatsapp'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class WhatsappApiWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'trig',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, 400],
    })
    WhenCalled = {
        workflowInputs: {
            values: [
                {
                    name: 'op',
                },
                {
                    name: 'params',
                    type: 'object',
                },
            ],
        },
    };

    @node({
        id: 'sw',
        name: 'Op Switch',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [240, 400],
    })
    OpSwitch = {
        rules: {
            values: [
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'send',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'sendDocument',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'sendImage',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'state',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'qr',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'disconnect',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'broadcast',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'createGroup',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                leftValue: '={{ $json.op }}',
                                rightValue: 'groupParticipants',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
        },
    };

    @node({
        id: 'done',
        name: 'Done',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [980, 400],
    })
    Done = {};

    @node({
        id: 'wunk',
        name: 'Unknown op',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [740, 860],
    })
    UnknownOp = {
        jsCode: `const op = $('When Called').first().json.op;
throw new Error(\`whatsapp api: unknown op '\${op}'. Known: send, sendDocument, sendImage, state, qr, disconnect, broadcast, createGroup, groupParticipants\`);`,
    };

    @node({
        id: 'wsend',
        name: 'w:send',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 0],
        credentials: { httpBasicAuth: { id: 'BmKlKWiEeZAxNWyi', name: 'Chat Auth [env-managed]' } },
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    WSend = {
        method: 'POST',
        url: 'http://chat:3000/api/bot/send',
        options: {
            timeout: 120000,
            response: {
                response: {
                    neverError: true,
                    fullResponse: true,
                },
            },
        },
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ JSON.stringify($json.params || {}) }}',
    };

    @node({
        id: 'wsdoc',
        name: 'w:sendDocument',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 96],
        credentials: { httpBasicAuth: { id: 'BmKlKWiEeZAxNWyi', name: 'Chat Auth [env-managed]' } },
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    WSenddocument = {
        method: 'POST',
        url: 'http://chat:3000/api/bot/send-document',
        options: {
            timeout: 120000,
            response: {
                response: {
                    neverError: true,
                    fullResponse: true,
                },
            },
        },
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ JSON.stringify($json.params || {}) }}',
    };

    @node({
        id: 'wsimg',
        name: 'w:sendImage',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 192],
        credentials: { httpBasicAuth: { id: 'BmKlKWiEeZAxNWyi', name: 'Chat Auth [env-managed]' } },
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    WSendimage = {
        method: 'POST',
        url: 'http://chat:3000/api/bot/send-image',
        options: {
            timeout: 120000,
            response: {
                response: {
                    neverError: true,
                    fullResponse: true,
                },
            },
        },
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ JSON.stringify($json.params || {}) }}',
    };

    @node({
        id: 'wstat',
        name: 'w:state',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 288],
        credentials: { httpBasicAuth: { id: 'BmKlKWiEeZAxNWyi', name: 'Chat Auth [env-managed]' } },
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    WState = {
        method: 'GET',
        url: 'http://chat:3000/api/bot/state',
        options: {
            timeout: 120000,
            response: {
                response: {
                    neverError: true,
                    fullResponse: true,
                },
            },
        },
        sendQuery: true,
        specifyQuery: 'json',
        jsonQuery: '={{ JSON.stringify($json.params || {}) }}',
    };

    @node({
        id: 'wqr',
        name: 'w:qr',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 384],
        credentials: { httpBasicAuth: { id: 'BmKlKWiEeZAxNWyi', name: 'Chat Auth [env-managed]' } },
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    WQr = {
        method: 'GET',
        url: 'http://chat:3000/api/bot/qr',
        options: {
            timeout: 120000,
            response: {
                response: {
                    neverError: true,
                    fullResponse: true,
                },
            },
        },
        sendQuery: true,
        specifyQuery: 'json',
        jsonQuery: '={{ JSON.stringify($json.params || {}) }}',
    };

    @node({
        id: 'wdisc',
        name: 'w:disconnect',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 480],
        credentials: { httpBasicAuth: { id: 'BmKlKWiEeZAxNWyi', name: 'Chat Auth [env-managed]' } },
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    WDisconnect = {
        method: 'POST',
        url: 'http://chat:3000/api/bot/disconnect',
        options: {
            timeout: 120000,
            response: {
                response: {
                    neverError: true,
                    fullResponse: true,
                },
            },
        },
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ JSON.stringify($json.params || {}) }}',
    };

    @node({
        id: 'wbcast',
        name: 'w:broadcast',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 576],
        credentials: { httpBasicAuth: { id: 'BmKlKWiEeZAxNWyi', name: 'Chat Auth [env-managed]' } },
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    WBroadcast = {
        method: 'POST',
        url: 'http://chat:3000/api/bot/broadcast',
        options: {
            timeout: 120000,
            response: {
                response: {
                    neverError: true,
                    fullResponse: true,
                },
            },
        },
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ JSON.stringify($json.params || {}) }}',
    };

    @node({
        id: 'wcgrp',
        name: 'w:createGroup',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 672],
        credentials: { httpBasicAuth: { id: 'BmKlKWiEeZAxNWyi', name: 'Chat Auth [env-managed]' } },
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    WCreategroup = {
        method: 'POST',
        url: 'http://chat:3000/api/bot/create-group',
        options: {
            timeout: 120000,
            response: {
                response: {
                    neverError: true,
                    fullResponse: true,
                },
            },
        },
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ JSON.stringify($json.params || {}) }}',
    };

    @node({
        id: 'wgprt',
        name: 'w:groupParticipants',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [512, 768],
        credentials: { httpBasicAuth: { id: 'BmKlKWiEeZAxNWyi', name: 'Chat Auth [env-managed]' } },
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    WGroupparticipants = {
        method: 'GET',
        url: 'http://chat:3000/api/bot/group-participants',
        options: {
            timeout: 120000,
            response: {
                response: {
                    neverError: true,
                    fullResponse: true,
                },
            },
        },
        sendQuery: true,
        specifyQuery: 'json',
        jsonQuery: '={{ JSON.stringify($json.params || {}) }}',
    };

    @node({
        id: 'wshape',
        name: 'Shape reply',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [740, 400],
    })
    ShapeReply = {
        jsCode: `// chat answers 200 with {success:false,...} for domain failures and a real
// status for transport failures. Callers should not have to know which: flatten both into
// {ok, status, data, error} and let \`ok\` be the single question worth asking.
const src = $('When Called').first().json;
return $input.all().map(i => {
  const st = i.json.statusCode ?? 200;
  const body = i.json.body ?? i.json;
  const ok = st >= 200 && st < 300 && body?.success !== false;
  return { json: { ok, status: st, op: src.op, data: body,
                   error: ok ? null : (body?.error || body?.message || \`HTTP \${st}\`) } };
});`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenCalled.out(0).to(this.OpSwitch.in(0));
        this.OpSwitch.out(0).to(this.WSend.in(0));
        this.OpSwitch.out(1).to(this.WSenddocument.in(0));
        this.OpSwitch.out(2).to(this.WSendimage.in(0));
        this.OpSwitch.out(3).to(this.WState.in(0));
        this.OpSwitch.out(4).to(this.WQr.in(0));
        this.OpSwitch.out(5).to(this.WDisconnect.in(0));
        this.OpSwitch.out(6).to(this.WBroadcast.in(0));
        this.OpSwitch.out(7).to(this.WCreategroup.in(0));
        this.OpSwitch.out(8).to(this.WGroupparticipants.in(0));
        this.OpSwitch.out(9).to(this.UnknownOp.in(0));
        this.WSend.out(0).to(this.ShapeReply.in(0));
        this.WSenddocument.out(0).to(this.ShapeReply.in(0));
        this.WSendimage.out(0).to(this.ShapeReply.in(0));
        this.WState.out(0).to(this.ShapeReply.in(0));
        this.WQr.out(0).to(this.ShapeReply.in(0));
        this.WDisconnect.out(0).to(this.ShapeReply.in(0));
        this.WBroadcast.out(0).to(this.ShapeReply.in(0));
        this.WCreategroup.out(0).to(this.ShapeReply.in(0));
        this.WGroupparticipants.out(0).to(this.ShapeReply.in(0));
        this.ShapeReply.out(0).to(this.Done.in(0));
    }
}
