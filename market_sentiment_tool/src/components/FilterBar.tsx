import { Button } from "@/components/ui/button";

interface FilterBarProps {
  options: string[];
  activeFilter: string | null;
  onFilterChange: (filter: string | null) => void;
}

export function FilterBar({ options, activeFilter, onFilterChange }: FilterBarProps) {
  return (
    <div className="flex flex-wrap gap-2 mb-6 p-1 bg-muted/30 rounded-lg w-fit">
      <Button
        variant={activeFilter === null ? "default" : "ghost"}
        size="sm"
        onClick={() => onFilterChange(null)}
        className="rounded-md"
      >
        All
      </Button>
      {options.map((opt) => (
        <Button
          key={opt}
          variant={activeFilter === opt ? "default" : "ghost"}
          size="sm"
          onClick={() => onFilterChange(opt)}
          className="rounded-md"
        >
          {opt}
        </Button>
      ))}
    </div>
  );
}
