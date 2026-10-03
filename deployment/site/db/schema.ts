import { sqliteTable, text, integer } from "drizzle-orm/sqlite-core";

// Counts attempts only. No documents, IP addresses, identities or API keys.
export const inferenceBudget = sqliteTable("inference_budget", {
  day: text("day").primaryKey(),
  attempts: integer("attempts").notNull().default(0),
});
