/** Экран 3: Клиенты 360° (реестр + карточка) — обёртка над Customer360
    с URL-роутингом (?contact=). */
import { useSearchParams } from "../hooks";
import Customer360 from "../components/Customer360";

export default function Customer360Page({
  onOpenCall,
}: {
  onOpenCall: (id: string) => void;
}) {
  const [query, setQuery] = useSearchParams();
  const contactId = query.get("contact");

  const selectContact = (id: string | null) => {
    if (id) setQuery({ contact: id });
    else setQuery({});
  };

  return (
    <Customer360
      contactId={contactId}
      onSelectContact={selectContact}
      onOpenCall={onOpenCall}
      onBack={() => {
        window.location.pathname = "/dashboard";
        window.dispatchEvent(new PopStateEvent("popstate"));
      }}
    />
  );
}
