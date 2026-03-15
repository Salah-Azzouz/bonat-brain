/**
 * Mock MongoDB layer — uses in-memory storage instead of real MongoDB.
 */

interface UserDoc {
  user_id: string;
  email: string;
  hashed_password: string;
  created_at: Date;
  last_login: Date | null;
  previous_login: Date | null;
  last_insight_date: Date | null;
  insight_shown_count: number;
  preferred_language: string;
  monthly_prompt_shown?: Date | null;
  monthly_report_offered?: Date | null;
}

interface HistoryDoc {
  user_id: string;
  merchant_id: string;
  conversation_id: string;
  user_query: string;
  ai_response: string;
  message_id: string;
  timestamp: Date;
  entities?: Record<string, unknown>;
}

interface ConversationDoc {
  conversation_id: string;
  user_id: string;
  merchant_id: string;
  created_at: Date;
}

// In-memory stores
const usersStore: UserDoc[] = [];
const historyStore: HistoryDoc[] = [];
const conversationsStore: ConversationDoc[] = [];

// Mock collection that mimics MongoDB Collection interface
function createMockCollection<T extends Record<string, unknown>>(store: T[]) {
  return {
    findOne: async (filter: Partial<T>) => {
      return store.find(doc => {
        return Object.entries(filter).every(([key, value]) => {
          return (doc as Record<string, unknown>)[key] === value;
        });
      }) || null;
    },
    find: (filter: Partial<T>) => {
      const results = store.filter(doc => {
        return Object.entries(filter).every(([key, value]) => {
          return (doc as Record<string, unknown>)[key] === value;
        });
      });
      return {
        sort: (sortSpec: Record<string, number>) => {
          const key = Object.keys(sortSpec)[0];
          const dir = Object.values(sortSpec)[0];
          results.sort((a, b) => {
            const aVal = (a as Record<string, unknown>)[key];
            const bVal = (b as Record<string, unknown>)[key];
            if (aVal === bVal) return 0;
            if (aVal === null || aVal === undefined) return 1;
            if (bVal === null || bVal === undefined) return -1;
            return dir > 0
              ? (aVal > bVal ? 1 : -1)
              : (aVal < bVal ? 1 : -1);
          });
          return {
            limit: (n: number) => ({
              toArray: async () => results.slice(0, n),
            }),
            toArray: async () => results,
          };
        },
        limit: (n: number) => ({
          toArray: async () => results.slice(0, n),
        }),
        toArray: async () => results,
      };
    },
    insertOne: async (doc: T) => {
      store.push(doc);
      return { insertedId: Math.random().toString(36) };
    },
    updateOne: async (filter: Partial<T>, update: { $set?: Partial<T>; $inc?: Partial<T> }) => {
      const idx = store.findIndex(doc => {
        return Object.entries(filter).every(([key, value]) => {
          return (doc as Record<string, unknown>)[key] === value;
        });
      });
      if (idx >= 0) {
        if (update.$set) {
          Object.assign(store[idx], update.$set);
        }
        if (update.$inc) {
          for (const [key, value] of Object.entries(update.$inc)) {
            const current = (store[idx] as Record<string, unknown>)[key] as number || 0;
            (store[idx] as Record<string, unknown>)[key] = current + (value as number);
          }
        }
        return { modifiedCount: 1 };
      }
      return { modifiedCount: 0 };
    },
    deleteMany: async (filter: Partial<T>) => {
      const before = store.length;
      const remaining = store.filter(doc => {
        return !Object.entries(filter).every(([key, value]) => {
          return (doc as Record<string, unknown>)[key] === value;
        });
      });
      store.length = 0;
      store.push(...remaining);
      return { deletedCount: before - store.length };
    },
    createIndex: async () => {},
  };
}

export interface MongoCollections {
  users: ReturnType<typeof createMockCollection>;
  conversations: ReturnType<typeof createMockCollection>;
  history: ReturnType<typeof createMockCollection>;
}

let _collections: MongoCollections | null = null;

export async function getMongoCollections(): Promise<MongoCollections | null> {
  if (!_collections) {
    _collections = {
      users: createMockCollection(usersStore as unknown as Record<string, unknown>[]),
      conversations: createMockCollection(conversationsStore as unknown as Record<string, unknown>[]),
      history: createMockCollection(historyStore as unknown as Record<string, unknown>[]),
    };
    console.log('[Mock MongoDB] Collections initialized');
  }
  return _collections;
}

export async function pingMongo(): Promise<boolean> {
  return true; // Mock always healthy
}
