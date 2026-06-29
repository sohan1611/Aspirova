import Link from "next/link";
import type { OpportunityListItem } from "@/lib/types";

export default function OpportunityCard({ item }: { item: OpportunityListItem }) {
  return (
    <Link
      href={`/opportunity/${item.slug}`}
      className="block rounded-lg border p-4 transition-colors hover:border-black"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-medium">{item.title}</h3>
          <p className="text-sm text-gray-600">
            {item.company?.name ?? "Unknown company"}
            {item.location ? ` · ${item.location}` : ""}
            {item.is_remote ? " · Remote" : ""}
          </p>
        </div>
        {item.category && (
          <span className="shrink-0 rounded-full bg-gray-100 px-2 py-1 text-xs whitespace-nowrap">
            {item.category}
          </span>
        )}
      </div>
      {item.deadline && (
        <p className="mt-2 text-xs text-amber-700">
          Deadline: {new Date(item.deadline).toLocaleDateString()}
          {item.deadline_confidence !== "explicit" ? " (estimated)" : ""}
        </p>
      )}
    </Link>
  );
}
